variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "instance_name" {
  description = "Value of the EC2 instance's Name tag; also the systemd unit and env-file name on the VM."
  type        = string
  default     = "opencompany"
}

variable "instance_type" {
  description = "The EC2 instance's type. t3.micro (2 vCPU, 1 GiB) is the smallest size the app runs on; 512 MB instances OOM-loop."
  type        = string
  default     = "t3.micro"
}

variable "root_volume_gb" {
  description = "Root gp3 volume size in GiB. A fresh install uses about 4.5 GiB."
  type        = number
  default     = 10
}

variable "key_name" {
  description = "Existing EC2 key pair name for SSH. Empty = no key pair."
  type        = string
  default     = ""
}

variable "port" {
  description = "Public port the app binds and the security group opens. The server rejects ports below 1024; 80/443 are left for a TLS front door."
  type        = number
  default     = 5678
}

variable "allow_cidr" {
  description = "Security group source range (e.g. 0.0.0.0/0 or <your-ip>/32)."
  type        = string
  default     = "0.0.0.0/0"
}

variable "opencompany_version" {
  description = "opencompany version to install from npm. Empty = latest."
  type        = string
  default     = ""
}

variable "install_sh_url" {
  description = "URL of the OpenCompany install script the first boot runs. Override to test an unreleased installer."
  type        = string
  default     = "https://opencompany.sh/install.sh"
}

variable "app_env" {
  description = "KEY=VALUE map rendered into the VM's systemd EnvironmentFile. Generate with cli/commands/deploy/_secrets.py build_app_env(port=<port>)."
  type        = map(string)
  sensitive   = true
}
