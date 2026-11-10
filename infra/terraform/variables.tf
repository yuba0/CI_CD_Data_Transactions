variable "project" {
  description = "Préfixe des ressources"
  type        = string
  default     = "transactions-pipeline"
}

variable "region" {
  type    = string
  default = "eu-west-3" # Paris
}

variable "processor_image" {
  description = "Image Docker du traitement (ex : ghcr.io/yuba0/ci_cd_data_transactions:abc1234), publique"
  type        = string
}

variable "process_interval" {
  description = "Intervalle (s) entre deux vérifications du bucket"
  type        = number
  default     = 60
}

variable "instance_type" {
  type    = string
  default = "t3.small"
}

variable "ssh_cidr" {
  description = "CIDR autorisé en SSH sur la VM (ex : ton IP/32). Vide = pas de SSH."
  type        = string
  default     = ""
}

variable "ssh_public_key" {
  description = "Clé publique SSH pour la VM (vide = pas de clé)"
  type        = string
  default     = ""
}
