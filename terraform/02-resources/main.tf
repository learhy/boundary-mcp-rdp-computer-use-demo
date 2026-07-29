# Step 2: Provision Boundary Resources
#
# Run this after step 01-cluster has created the HCP Boundary cluster:
#   terraform init && terraform apply
#
# Uses the cluster URL from step 1. You need to set:
#   TF_VAR_boundary_addr = the cluster URL from step 1 output
#   TF_VAR_boundary_admin_password = the admin password from step 1

terraform {
  required_providers {
    boundary = {
      source  = "hashicorp/boundary"
      version = "~> 1.1"
    }
  }
}

variable "boundary_addr" {
  type = string
}

variable "boundary_admin_username" {
  type    = string
  default = "admin"
}

variable "boundary_admin_password" {
  type      = string
  sensitive = true
}

variable "windows_host_ip" {
  type = string
}

variable "windows_username" {
  type    = string
  default = "Administrator"
}

variable "windows_password" {
  type      = string
  sensitive = true
}

variable "minio_endpoint" {
  type = string
}

variable "minio_access_key" {
  type    = string
  default = "minioadmin"
}

variable "minio_secret_key" {
  type      = string
  default   = "minioadmin123"
  sensitive = true
}

variable "minio_bucket_name" {
  type    = string
  default = "boundary-session-recordings"
}

variable "enable_recording" {
  type        = bool
  description = "Enable session recording. Requires a reachable S3-compatible storage endpoint."
  default     = false
}

provider "boundary" {
  addr                   = var.boundary_addr
  auth_method_login_name = var.boundary_admin_username
  auth_method_password   = var.boundary_admin_password
}

resource "boundary_scope" "org" {
  name        = "rdp-org"
  description = "RDP Computer Use Demo Org"
  scope_id    = "global"
}

resource "boundary_scope" "project" {
  name        = "rdp-project"
  description = "RDP Computer Use Demo Project"
  scope_id    = boundary_scope.org.id
}

resource "boundary_host_catalog_static" "windows" {
  name        = "windows-hosts"
  description = "Windows host catalog"
  scope_id    = boundary_scope.project.id
}

resource "boundary_host_static" "windows_vm" {
  name            = "windows-remote"
  description     = "Remote Windows host (AWS EC2)"
  host_catalog_id = boundary_host_catalog_static.windows.id
  address         = var.windows_host_ip
}

resource "boundary_host_set_static" "windows" {
  name            = "windows-remote-set"
  description     = "Host set containing the Windows host"
  host_catalog_id = boundary_host_catalog_static.windows.id
  host_ids        = [boundary_host_static.windows_vm.id]
}

resource "boundary_credential_store_static" "windows" {
  name        = "windows-creds"
  description = "Windows credential store"
  scope_id    = boundary_scope.project.id
}

resource "boundary_credential_username_password" "windows_admin" {
  name                = "windows-admin"
  description         = "Windows Administrator credentials"
  credential_store_id = boundary_credential_store_static.windows.id
  username            = var.windows_username
  password            = var.windows_password
}

resource "boundary_storage_bucket" "recordings" {
  count         = var.enable_recording ? 1 : 0
  name          = "session-recording-bucket"
  description   = "MinIO S3 bucket for RDP session recordings"
  scope_id      = boundary_scope.org.id
  bucket_name   = var.minio_bucket_name
  plugin_name   = "minio"
  worker_filter = "\"worker-session-recording\" in \"/tags/type\""
  attributes_json = jsonencode({
    endpoint_url                = var.minio_endpoint
    region                      = "us-east-1"
    disable_credential_rotation = true
  })
  secrets_json = jsonencode({
    access_key_id     = var.minio_access_key
    secret_access_key = var.minio_secret_key
  })
}

resource "boundary_target" "windows_rdp" {
  type                           = "tcp"
  name                           = "windows-rdp"
  description                    = "Windows RDP target (TCP port 3389)"
  scope_id                       = boundary_scope.project.id
  default_port                   = 3389
  host_source_ids                = [boundary_host_set_static.windows.id]
  brokered_credential_source_ids = [boundary_credential_username_password.windows_admin.id]
  session_max_seconds            = 3600
  enable_session_recording       = var.enable_recording
  storage_bucket_id              = var.enable_recording ? "sb_BgcbN7eRwj" : null
}

output "target_id" {
  value = boundary_target.windows_rdp.id
}

output "org_id" {
  value = boundary_scope.org.id
}

output "project_id" {
  value = boundary_scope.project.id
}

output "storage_bucket_id" {
  value = var.enable_recording ? boundary_storage_bucket.recordings[0].id : null
}

output "boundary_addr" {
  value = var.boundary_addr
}