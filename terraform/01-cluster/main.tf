# Step 1: Create the HCP Boundary Cluster
#
# This creates the HCP Boundary cluster. Run this first:
#   terraform init && terraform apply
#
# After the cluster is ready, run step 02-resources.

terraform {
  required_providers {
    hcp = {
      source  = "hashicorp/hcp"
      version = "~> 0.112.0"
    }
  }
}

provider "hcp" {
  client_id     = var.hcp_client_id
  client_secret = var.hcp_client_secret
}

variable "hcp_client_id" {
  type      = string
  sensitive = true
}

variable "hcp_client_secret" {
  type      = string
  sensitive = true
}

variable "boundary_cluster_id" {
  type    = string
  default = "rdp-demo-cluster"
}

variable "boundary_admin_username" {
  type    = string
  default = "admin"
}

variable "boundary_admin_password" {
  type      = string
  default   = "AdminPass123!"
  sensitive = true
}

resource "hcp_boundary_cluster" "rdp_demo" {
  cluster_id = var.boundary_cluster_id
  username   = var.boundary_admin_username
  password   = var.boundary_admin_password
  tier       = "Plus"
}

output "boundary_cluster_url" {
  value = hcp_boundary_cluster.rdp_demo.cluster_url
}

output "boundary_admin_username" {
  value = var.boundary_admin_username
}

output "boundary_admin_password" {
  value     = var.boundary_admin_password
  sensitive = true
}