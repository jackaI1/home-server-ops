terraform {
  required_providers {
    opensearch = { source = "opensearch-project/opensearch", version = "~> 2.0" }
  }
}
variable "endpoint" { default = "http://localhost:9200" }
provider "opensearch" { url = var.endpoint }
resource "opensearch_index" "events" {
  name = "home-events"
  number_of_shards = "1"
  number_of_replicas = "0"
}
resource "opensearch_index" "rules" {
  name = "home-detection-rules"
  number_of_shards = "1"
  number_of_replicas = "0"
}
resource "terraform_data" "deploy_rules" {
  triggers_replace = [for path in sort(fileset("${path.module}/../rules", "*.yml")) : filesha256("${path.module}/../rules/${path}")]
  depends_on = [opensearch_index.rules]
  provisioner "local-exec" {
    command = "python3 ${path.module}/../deploy.py ${var.endpoint}"
  }
}
