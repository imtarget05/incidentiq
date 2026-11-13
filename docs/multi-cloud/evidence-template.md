# Multi-Cloud Evidence Template (P1 — chưa chạy thật) — IncidentIQ

Mục tiêu: chứng minh khả năng cloud-agnostic bằng cách deploy cùng workload lên ≥2 cloud.
**Lưu ý**: Các bước dưới đây là skeleton/template. Để lấy evidence thật, bạn cần credentials cloud thật (Azure/AWS/GCP) và thay các giá trị `CHANGE_ME`.

## 1. Mục tiêu evidence

| Mục tiêu | Cloud 1 (hiện có) | Cloud 2 (cần bổ sung) |
|----------|-------------------|-----------------------|
| K8s cluster | Azure AKS (Terraform) | AWS EKS hoặc GCP GKE |
| PostgreSQL | Azure PG Flexible | AWS RDS / GCP Cloud SQL |
| Object storage | Azure Storage | AWS S3 / GCP GCS |
| Redis | Azure Cache for Redis | AWS ElastiCache / GCP Memorystore |
| ArgoCD sync | Azure AKS | AWS EKS / GCP GKE |
| App health | /health/live 200 | /health/live 200 |

## 2. Skeleton Terraform AWS (placeholder)

```hcl
# infrastructure/terraform/aws/main.tf  (chưa được kích hoạt)
provider "aws" {
  region = var.aws_region
}

resource "aws_eks_cluster" "incidentiq" {
  name     = "incidentiq-eks"
  role_arn = aws_iam_role.cluster.arn
  version  = "1.28"

  vpc_config {
    subnet_ids = aws_subnet.eks[*].id
  }
}

resource "aws_rds_cluster" "incidentiq_pg" {
  cluster_identifier = "incidentiq-pg"
  engine             = "aurora-postgresql"
  master_username    = var.pg_admin_user
  master_password    = var.pg_admin_password  # từ secret, không hardcode
}
```

## 3. Checklist evidence (điền khi chạy thật)

- [ ] Terraform apply Azure AKS thành công → `terraform output kubernetes_cluster_name`
- [ ] Terraform apply AWS/GCP EKS/GKE thành công → cluster_name
- [ ] ArgoCD Application deploy cùng Helm chart lên cả 2 cluster
- [ ] `kubectl get pods -n incidentiq-prod` trên cả 2 cluster đều Running
- [ ] `curl <LB-IP>/health/live` trả 200 trên cả 2 cloud
- [ ] Chụp màn hình / lưu logs làm evidence đính kèm vào CV/portfolio

## 4. Cách lấy screenshot evidence

```bash
# Trên mỗi cloud, sau khi deploy:
kubectl get pods -n incidentiq-prod -o wide > evidence/cluster-<cloud>-pods.txt
curl -s <LB-IP>/health/live > evidence/health-<cloud>.json
kubectl get rollout -n incidentiq-prod > evidence/rollout-<cloud>.txt
# Chụp màn hình Grafana dashboard + ArgoCD sync status
```
