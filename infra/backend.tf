terraform {
  backend "s3" {
    bucket         = "sentellent-tfstate-bucket"
    key            = "sentellent/infra/terraform.tfstate"
    region         = "ap-south-1"
    dynamodb_table = "sentellent-tf-locks"
    encrypt        = true
  }
}
