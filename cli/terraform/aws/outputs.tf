output "instance_id" {
  description = "ID of the EC2 instance."
  value       = aws_instance.app_server.id
}

output "instance_public_ip" {
  description = "Public IP of the EC2 instance (changes on stop/start unless an Elastic IP is attached)."
  value       = aws_instance.app_server.public_ip
}

output "url" {
  description = "The app URL (login gate)."
  value       = "http://${aws_instance.app_server.public_ip}:${var.port}"
}
