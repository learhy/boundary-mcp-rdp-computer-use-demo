# Boundary Worker Configuration for RDP Demo
# Self-managed worker connected to HCP Boundary cluster
# Has recording storage enabled for session recording

# Worker public address - this server's public IP
# The worker listens for proxy connections on port 9322
public_addr = "178.104.180.23:9322"

# Recording storage directory
recording_storage_directory = "/tmp/boundary-recordings"

# Initial workers auth token (from controller-led worker creation)
initial_upstream_authorities = [
  "/certs/boundary-controller-ca.pem"
]

# Debug logging
debug = true

# The worker connects to the HCP Boundary controller
# The activation token is passed via the BOUNDARY_TOKEN env var when starting

listener "tcp" {
  address = "0.0.0.0:9322"
  purpose = "proxy"
}

worker {
  worker_generated_network_parameters {
    private_addr = "100.81.87.22"
    public_addr  = "178.104.180.23:9322"
  }
}