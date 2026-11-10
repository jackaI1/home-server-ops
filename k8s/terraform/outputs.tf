output "namespace" {
  value = kubernetes_namespace_v1.home_ops.metadata[0].name
}

output "release_status" {
  value = helm_release.home_ops.status
}

output "port_forward_command" {
  description = "Run this to reach the API from your laptop without exposing it to the network."
  value       = "kubectl -n ${kubernetes_namespace_v1.home_ops.metadata[0].name} port-forward service/telemetry 8000:80"
}
