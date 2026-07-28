# Boundary MCP RDP Computer Use Demo - HCP Boundary Terraform
#
# Provisions all Boundary resources on HCP Boundary for the RDP computer use demo.
# Session recording is supported on HCP Boundary (Enterprise).
#
# Usage:
#   1. Set environment variables:
#      export BOUNDARY_ADDR=https://<your-cluster>.boundary.hashicorp.cloud
#      export BOUNDARY_ADMIN_AUTH_METHOD_ID=ampw_XXXXXXXX  # from HCP admin
#      export BOUNDARY_ADMIN_PASSWORD=XXXXXXXX              # admin password
#      export TF_VAR_windows_host_ip=ec2-xx-xx-xx-xx.compute.amazonaws.com
#      export TF_VAR_windows_username=Administrator
#      export TF_VAR_windows_password=YourPassword123
#      export TF_VAR_minio_endpoint=http://<minio-host>:9000
#      export TF_VAR_minio_access_key=minioadmin
#      export TF_VAR_minio_secret_key=minioadmin123
#
#   2. Initialize and apply:
#      terraform init
#      terraform apply
#
#   3. The output gives you the target ID and auth token for the MCP config.

terraform {
  required_providers {
    boundary = {
      source  = "hashicorp/boundary"
      version = "~> 1.1"
    }
  }
}

provider "boundary" {
  addr                   = var.boundary_addr
  auth_method_id         = var.boundary_auth_method_id
  auth_method_login_name = "admin"
  auth_method_password   = var.boundary_admin_password
}

variable "boundary_addr" {
  type        = string
  description = "HCP Boundary cluster URL (e.g. https://xxx.boundary.hashicorp.cloud)"
}

variable "boundary_auth_method_id" {
  type        = string
  description = "Auth method ID for the admin user (e.g. ampw_xxx)"
}

variable "boundary_admin_password" {
  type        = string
  description = "Admin password for HCP Boundary"
  sensitive   = true
}

variable "windows_host_ip" {
  type        = string
  description = "IP or hostname of the remote Windows host (RDP on port 3389)"
}

variable "windows_username" {
  type        = string
  description = "Windows RDP username"
  default     = "Administrator"
}

variable "windows_password" {
  type        = string
  description = "Windows RDP password"
  sensitive   = true
}

variable "minio_endpoint" {
  type        = string
  description = "MinIO S3 API endpoint URL (reachable from HCP Boundary workers)"
}

variable "minio_access_key" {
  type        = string
  description = "MinIO access key"
  default     = "minioadmin"
}

variable "minio_secret_key" {
  type        = string
  description = "MinIO secret key"
  sensitive   = true
  default     = "minioadmin123"
}

variable "minio_bucket_name" {
  type        = string
  description = "MinIO bucket name for session recordings"
  default     = "boundary-session-recordings"
}

# ── Org and Project ──────────────────────────────────────────────────────

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

# ── Host Catalog, Host, Host Set ─────────────────────────────────────────

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

# ── Credential Store and Credential ──────────────────────────────────────

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

# ── Storage Bucket for Session Recordings ───────────────────────────────
# This is an Enterprise feature. On HCP Boundary, storage buckets are supported.

resource "boundary_storage_bucket" "recordings" {
  name          = "session-recording-bucket"
  description   = "MinIO S3 bucket for RDP session recordings"
  scope_id      = boundary_scope.project.id
  bucket_name   = var.minio_bucket_name
  plugin_name   = "aws"
  worker_filter = "\"true\" in \"/tags/all\""
  attributes_json = jsonencode({
    bucket_name = var.minio_bucket_name
    region      = "us-east-1"
    access_key  = var.minio_access_key
    endpoint    = var.minio_endpoint
  })
  secrets_json = jsonencode({
    secret_access_key = var.minio_secret_key
  })
}

# ── RDP Target with Session Recording ───────────────────────────────────

resource "boundary_target" "windows_rdp" {
  name                           = "windows-rdp"
  description                    = "Windows RDP target (TCP port 3389)"
  scope_id                       = boundary_scope.project.id
  type                           = "tcp"
  default_port                   = 3389
  host_source_ids                = [boundary_host_set_static.windows.id]
  brokered_credential_source_ids = [boundary_credential_username_password.windows_admin.id]
  session_max_seconds            = 3600

  # Session recording (Enterprise / HCP Boundary)
  enable_session_recording = true
  storage_bucket_id        = boundary_storage_bucket.recordings.id
}

# ── Outputs ─────────────────────────────────────────────────────────────

output "org_id" {
  value = boundary_scope.org.id
}

output "project_id" {
  value = boundary_scope.project.id
}

output "host_catalog_id" {
  value = boundary_host_catalog_static.windows.id
}

output "host_id" {
  value = boundary_host_static.windows_vm.id
}

output "host_set_id" {
  value = boundary_host_set_static.windows.id
}

output "credential_store_id" {
  value = boundary_credential_store_static.windows.id
}

output "credential_id" {
  value = boundary_credential_username_password.windows_admin.id
}

output "storage_bucket_id" {
  value = boundary_storage_bucket.recordings.id
}

output "target_id" {
  value = boundary_target.windows_rdp.id
}

output "boundary_addr" {
  value = var.boundary_addr
}