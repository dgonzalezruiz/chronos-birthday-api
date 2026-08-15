# Production Architecture: Chronos Birthday API on AWS

## 1. Context & Scope

The Chronos Birthday API is a small sample microservice with two endpoints (`PUT /hello/{username}` and `GET /hello/{username}`) backed by a relational database. It is intended as a sample service rather than a production application.

This document describes the AWS infrastructure we would use to run a similar microservice in production, with high availability and sustained traffic in mind. The proposed architecture uses **Amazon EKS** across three Availability Zones (`us-east-1a`, `us-east-1b`, and `us-east-1c`) with a managed **Amazon Aurora PostgreSQL** cluster. It also considers standard Amazon RDS and running PostgreSQL inside the Kubernetes cluster as alternatives.

---

## 2. Target Architecture

<p align="center">
  <img src="assets/architecture.svg" alt="AWS Production Architecture" width="100%">
</p>

---

## 3. Infrastructure & Platform Walkthrough

### 3.1 Ingress & Network Path

* **VPC Layout:** The VPC spans three Availability Zones, with public and private subnets provisioned through Terraform. Public subnets contain only the internet-facing Application Load Balancer and NAT Gateways. EKS worker nodes, database subnets, and VPC interface endpoints remain in private subnets and do not have public IP addresses.

* **Edge Routing & Filtering:** Route 53 routes incoming DNS requests to a Multi-AZ Application Load Balancer. An AWS WAF WebACL is attached to the ALB to provide IP-based rate limiting and inspect requests against AWS Managed Rules for common web exploits. TLS is terminated at the ALB using certificates managed by AWS Certificate Manager (ACM).

* **Pod Ingress:** Ingress is handled by the AWS Load Balancer Controller using `ip` target mode. Together with the AWS VPC CNI, this allows the ALB target group to send traffic directly to pod ENI IP addresses instead of routing through `kube-proxy` NodePort hops, reducing unnecessary network hops and internal NAT overhead.

### 3.2 Compute & Scaling (Amazon EKS)

* **Cluster Control Plane:** The cluster uses managed EKS with private endpoint access and KMS envelope encryption enabled for Kubernetes Secrets.

* **Horizontal Pod Autoscaling (HPA):** The HPA scales API pods across the Availability Zones based on CPU utilization. For sudden traffic spikes where CPU metrics may not react quickly enough, custom HTTP request-rate metrics can also be exposed to the HPA through `prometheus-adapter`.

* **Node Elasticity (Karpenter):** Karpenter handles node capacity dynamically across the Availability Zones. When pods cannot be scheduled, it provisions appropriately sized EC2 instances based on the workloads that are actually pending. The setup can use a mix of ARM64 and AMD64 instances, as well as Spot capacity, avoiding the warm-up delays associated with maintaining large static Auto Scaling Groups.

* **High Availability Controls:** Pods use `topologySpreadConstraints` on `topology.kubernetes.io/zone` with `maxSkew: 1` to keep replicas distributed across all three Availability Zones. A `PodDisruptionBudget` with `minAvailable: 2` ensures that voluntary node drains and rolling upgrades do not reduce the available capacity below the required level.

### 3.3 Database Tier & State Persistence

For relational persistence in a production AWS environment, there are three main approaches worth considering, hence why the storage layer has been modeled as "Storage Black Box" in the diagram. The following sections compare them before covering a few additional operational considerations.

#### 3.3.1 Amazon Aurora PostgreSQL (Multi-AZ) — Selected Production Baseline

**High Availability & Storage:** Aurora uses shared, distributed storage replicated six ways across three Availability Zones. Storage scales automatically in 10 GB increments, up to 128 TiB, without requiring manual disk resizing or EBS volume modification windows.

**Failover Performance:** If the primary instance fails, Aurora can promote a read replica to the writer role in roughly 15 seconds by updating the DNS writer endpoint, without going through a traditional storage detach and reattach process.

**Backups & Recovery:** Aurora continuously streams write-ahead logs to Amazon S3, providing point-in-time recovery (PITR) down to the second without adding the same kind of backup workload to the active database instance.

#### 3.3.2 Amazon RDS PostgreSQL (Multi-AZ) — Standard Managed Alternative

**Topology:** A primary database instance runs in one Availability Zone, with a synchronous standby replica in a second AZ using block-level EBS replication.

**Trade-offs:** RDS provides a predictable baseline cost and is roughly 20–30% cheaper than Aurora for compute and storage in this comparison. The trade-off is longer failover time, which can take around 60–120 seconds while the standby assumes the writer role and completes crash recovery. Storage is based on provisioned gp3 volumes, so expansion needs to be monitored and planned around storage modification cooldown periods.

#### 3.3.3 In-Cluster Operator (CloudNativePG / Percona) — Cloud-Neutral Alternative

* **Topology:** A three-node PostgreSQL cluster runs on Kubernetes worker nodes distributed across the three Availability Zones. Each instance uses a StatefulSet and its own gp3 EBS volume.

* **Trade-offs:** This approach is highly portable and can be managed through the same GitOps workflow as the rest of the Kubernetes platform. It also avoids paying for a managed database service. However, the platform team becomes responsible for the database operator lifecycle, storage capacity, backup validation, and recovery testing.

#### 3.3.4 Additional Considerations

* **Connection Pooling (Amazon RDS Proxy):** Rapid HPA scale-outs—for example, going from 3 to 30 API pods—can quickly consume the PostgreSQL connection limit. An Amazon RDS Proxy instance between the EKS pods and the database can help by pooling and multiplexing connections.

* **Schema Migrations:** Local development currently uses `Base.metadata.create_all` to create the PostgreSQL schema when the application starts. In production, schema changes should instead run separately through an Alembic Kubernetes Job as part of the deployment pipeline, before the new application pods are rolled out. This avoids multiple pods trying to perform DDL operations against the primary database at the same time.

### 3.4 Workload Identity & Security

* **IAM Roles for Service Accounts (IRSA):** Pods access AWS services such as S3 and Secrets Manager using temporary STS credentials through the cluster's OIDC provider. This avoids storing long-lived IAM access keys inside the cluster.

* **Secrets Synchronization:** Database connection strings and credentials are stored in AWS Secrets Manager and synchronized into Kubernetes Secrets using the External Secrets Operator (ESO).

* **Container Hardening:** Containers run as an unprivileged, non-root user (`appuser`, UID 10001), drop all Linux capabilities (`drop: ["ALL"]`), and use a read-only root filesystem.

---

## 4. Required Helm Chart Components

The Helm chart in `helm/chronos-birthday-api` contains the following core manifests needed to deploy the application cleanly to Kubernetes:

| File / Manifest                                      | Role in the Deployment                                                                                                                                           |
| :--------------------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Chart.yaml`                                         | Defines chart metadata, API version (`v2`), semantic versions (`version`, `appVersion`), and dependencies.                                                       |
| `values.yaml`                                        | Provides the main configuration interface for environment-specific settings such as replica counts, image tags, resource limits, probe paths, and ingress rules. |
| `templates/_helpers.tpl`                             | Contains reusable Go template helpers for consistent resource names and metadata labels such as `app.kubernetes.io/name`.                                        |
| `templates/deployment.yaml`                          | Defines the application workload, including container images, environment variables, security contexts, and `/healthz` health probes.                            |
| `templates/service.yaml`                             | Creates a stable internal `ClusterIP` service that distributes traffic across available pod endpoints.                                                           |
| `templates/ingress.yaml`                             | Defines external HTTP/HTTPS routing, host matching, and ALB ingress controller annotations.                                                                      |
| `templates/configmap.yaml` & `templates/secret.yaml` | Provide runtime configuration and database connection credentials to the application.                                                                            |
| `templates/hpa.yaml`                                 | Configures the Horizontal Pod Autoscaler, including scaling limits and metric thresholds.                                                                        |
| `templates/pdb.yaml`                                 | Defines `PodDisruptionBudget` rules to maintain minimum pod availability during node maintenance.                                                                |
| `templates/serviceaccount.yaml`                      | Associates the workload with Kubernetes RBAC permissions and the AWS IRSA IAM role.                                                                              |

---

### 5.2 Decision Rationale

#### Why Aurora PostgreSQL Over Standard RDS & In-Cluster Operators?

* **Over In-Cluster Operators:** Running PostgreSQL inside EKS with an operator such as CloudNativePG provides portability and avoids the premium of a managed database service. The downside is that the internal platform team takes responsibility for storage management, operator upgrades, backups, failover handling, and disaster recovery testing.

* **Over Standard RDS:** Standard RDS PostgreSQL Multi-AZ is a solid and well-understood option, but its block-level storage replication can result in longer failover times, typically around 60–120 seconds in this comparison. It also relies on provisioned EBS storage that needs to be monitored and expanded when necessary. For a workload where availability is a priority, Aurora's distributed storage architecture, multi-AZ replication, and faster failover make the additional cost worthwhile.

#### Why EKS Over Serverless?

For such a simple key-value access pattern (`username` → `dateOfBirth`), a serverless AWS stack using **API Gateway + Lambda + DynamoDB** would be a perfectly reasonable alternative. It can scale down to zero when idle and removes most of the infrastructure maintenance.

We chose the containerized **EKS + PostgreSQL** approach mainly for two reasons:

1. **Local and Production Parity:** The project requirements explicitly call for packaging and validating the application with a Helm chart. Running FastAPI in Kubernetes means we can use the same container image, configuration approach, and database drivers locally with `kind` during CI and then deploy the same setup to AWS.

2. **Platform & Database Portability:** Using standard FastAPI and PostgreSQL keeps the application largely independent of proprietary cloud database APIs. The same application can therefore run on other Kubernetes platforms, such as GKE or AKS, or in an on-premises environment without requiring changes to the core application logic or database access layer.

