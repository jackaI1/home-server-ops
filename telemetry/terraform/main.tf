terraform {
  required_providers {
    kubernetes = { source = "hashicorp/kubernetes", version = "~> 2.0" }
  }
}
provider "kubernetes" { config_path = "~/.kube/config" }
resource "kubernetes_namespace" "telemetry" {
  metadata { name = "telemetry" }
}
resource "kubernetes_manifest" "resources" {
  for_each = { for doc in split("\n---\n", file("${path.module}/../k8s/app.yaml")) : "${yamldecode(doc).kind}-${yamldecode(doc).metadata.name}" => yamldecode(doc) }
  manifest = merge(each.value, { metadata = merge(each.value.metadata, { namespace = kubernetes_namespace.telemetry.metadata[0].name }) })
}
