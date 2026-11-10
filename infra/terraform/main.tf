# Ressources de production dans AWS :
#   - S3 (bucket des fichiers entrants)
#   - RDS PostgreSQL (base des résultats)
#   - EC2 (VM qui exécute le conteneur de traitement en boucle)

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
}

resource "random_id" "suffix" {
  byte_length = 3
}

# ----------------------------------------------------------------------- S3
resource "aws_s3_bucket" "incoming" {
  bucket        = "${var.project}-${random_id.suffix.hex}"
  force_destroy = true # TP : permet terraform destroy même si non vide
}

resource "aws_s3_bucket_public_access_block" "incoming" {
  bucket                  = aws_s3_bucket.incoming.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "incoming" {
  bucket = aws_s3_bucket.incoming.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

# ---------------------------------------------------------------------- RDS
resource "random_password" "db" {
  length  = 24
  special = false
}

resource "aws_security_group" "vm" {
  name   = "${var.project}-vm"
  vpc_id = data.aws_vpc.default.id

  dynamic "ingress" {
    for_each = var.ssh_cidr == "" ? [] : [var.ssh_cidr]
    content {
      description = "SSH"
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "db" {
  name   = "${var.project}-db"
  vpc_id = data.aws_vpc.default.id

  ingress {
    description     = "PostgreSQL depuis la VM uniquement"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.vm.id]
  }
}

resource "aws_db_instance" "postgres" {
  identifier              = var.project
  engine                  = "postgres"
  engine_version          = "16"
  instance_class          = "db.t4g.micro"
  allocated_storage       = 20
  storage_encrypted       = true
  db_name                 = "transactions"
  username                = "pipeline"
  password                = random_password.db.result
  vpc_security_group_ids  = [aws_security_group.db.id]
  publicly_accessible     = false
  skip_final_snapshot     = true # TP uniquement
  backup_retention_period = 1
}

# ---------------------------------------------------------- IAM (VM -> S3)
resource "aws_iam_role" "vm" {
  name = "${var.project}-vm"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "vm_s3" {
  name = "s3-read-incoming"
  role = aws_iam_role.vm.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.incoming.arn },
      { Effect = "Allow", Action = ["s3:GetObject"], Resource = "${aws_s3_bucket.incoming.arn}/*" },
    ]
  })
}

resource "aws_iam_instance_profile" "vm" {
  name = "${var.project}-vm"
  role = aws_iam_role.vm.name
}

# ---------------------------------------------------------------------- EC2
resource "aws_key_pair" "vm" {
  count      = var.ssh_public_key == "" ? 0 : 1
  key_name   = var.project
  public_key = var.ssh_public_key
}

resource "aws_instance" "processor" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  subnet_id              = data.aws_subnets.default.ids[0]
  vpc_security_group_ids = [aws_security_group.vm.id]
  iam_instance_profile   = aws_iam_instance_profile.vm.name
  key_name               = var.ssh_public_key == "" ? null : aws_key_pair.vm[0].key_name

  metadata_options {
    http_tokens = "required" # IMDSv2
  }

  user_data_replace_on_change = true
  user_data = templatefile("${path.module}/cloud-init.sh.tftpl", {
    image            = var.processor_image
    process_interval = var.process_interval
    region           = var.region
    bucket           = aws_s3_bucket.incoming.bucket
    database_url     = "postgresql://pipeline:${random_password.db.result}@${aws_db_instance.postgres.endpoint}/transactions"
  })
}
