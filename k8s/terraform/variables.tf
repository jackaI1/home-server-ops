variable "kubeconfig_path" {
  description = "Kubeconfig for the target cluster (k3s on the home server, or a throwaway kind cluster in CI)."
  type        = string
  default     = "~/.kube/config"
}

variable "kube_context" {
  description = "Context inside the kubeconfig. Leave empty to use the current context."
  type        = string
  default     = ""
}

variable "namespace" {
  description = "Namespace that holds the telemetry API, PostgreSQL and backups."
  type        = string
  default     = "home-ops"
}

variable "chart_path" {
  description = "Path to the Helm chart. Defaults to the chart in this repository."
  type        = string
  default     = "../charts/home-ops"
}

variable "telemetry_image_repository" {
  description = "Image for the telemetry API. Build it from the repository root with telemetry/Dockerfile."
  type        = string
  default     = "telemetry"
}

variable "telemetry_image_tag" {
  description = "Tag of the telemetry image. Use a fixed tag so rollouts are predictable."
  type        = string
  default     = "local"
}

variable "postgres_password" {
  description = "Password for the telemetry database user. Letters and digits only, at least 24 characters. Pass it with TF_VAR_postgres_password, never commit it."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^[A-Za-z0-9]{24,}$", var.postgres_password))
    error_message = "postgres_password must be at least 24 letters or digits (no symbols, because it is embedded in a database URL)."
  }
}

variable "postgres_storage_size" {
  description = "Size of the PostgreSQL data volume."
  type        = string
  default     = "5Gi"
}

variable "storage_class" {
  description = "Storage class for the data and backup volumes. Empty uses the cluster default (local-path on k3s)."
  type        = string
  default     = ""
}

variable "backup_schedule" {
  description = "Cron schedule for pg_dump backups, in UTC."
  type        = string
  default     = "17 2 * * *"
}

variable "backup_retention_days" {
  description = "How many days of dumps to keep on the backup volume."
  type        = number
  default     = 14
}

variable "ingress_namespaces" {
  description = "Namespaces allowed to reach the telemetry API. k3s runs Traefik in kube-system."
  type        = list(string)
  default     = ["kube-system"]
}

variable "ingress_pod_labels" {
  description = "Pod labels in the same namespace allowed to reach the telemetry API, for example a client pod."
  type        = map(string)
  default     = {}
}
