# Cloudflare R2 Setup for Cloud Inventory Discovery — v0.5.1

## Purpose
The application uses Cloudflare R2 through its S3-compatible API for persistent object storage. This is separate from PostgreSQL. The R2 bucket should remain private; the application serves authorized downloads through its own authenticated endpoints.

## 1. Confirm R2 is enabled
In the Cloudflare dashboard, open **Storage & databases → R2 → Overview**. Complete the R2 subscription/activation flow if R2 has not yet been enabled for the account.

## 2. Create a staging bucket
From R2 Overview select **Create bucket**.

Recommended staging bucket name:

`cloud-inventory-discovery-staging`

Bucket names must be lowercase and may use numbers and hyphens. Keep the bucket private. Do not enable an `r2.dev` public URL for this application.

## 3. Record the Cloudflare Account ID
On the R2 Overview/API-token area, copy the Cloudflare **Account ID**. The standard S3-compatible endpoint is:

`https://ACCOUNT_ID.r2.cloudflarestorage.com`

Replace `ACCOUNT_ID` with the real account ID. Do not include angle brackets.

If the bucket was deliberately created in the EU jurisdiction, use the jurisdiction endpoint documented by Cloudflare, for example:

`https://ACCOUNT_ID.eu.r2.cloudflarestorage.com`

For a normal/default jurisdiction bucket use the standard endpoint.

## 4. Create R2 S3 credentials
In **R2 → Manage API Tokens**:
1. Create an **Account API token** for a service credential where your Cloudflare role permits it. A User API token can also be used if required by account permissions.
2. Give the token **Object Read & Write** permission.
3. Scope it to the staging bucket only where possible.
4. Create the token.
5. Copy both values immediately:
   - **Access Key ID**
   - **Secret Access Key**

The secret is only shown once. Do not use the general Cloudflare bearer-token value as the S3 Secret Access Key.

## 5. Update the Render staging web service
Open the Render service **cloud-inventory-discovery-staging → Environment** and set:

- `STORAGE_MODE` = `s3`
- `S3_ENDPOINT` = the real R2 S3 endpoint
- `S3_REGION` = `auto`
- `S3_BUCKET` = the exact R2 bucket name
- `S3_ACCESS_KEY_ID` = the R2 Access Key ID
- `S3_SECRET_ACCESS_KEY` = the R2 Secret Access Key

Save the changes. Do not include quotes or angle brackets in the values.

## 6. Update the Render staging worker
Open **cloud-inventory-discovery-staging-worker → Environment** and set the same five S3/R2 values. The web service and worker must point to the same bucket and credentials.

The Blueprint intentionally uses `sync: false` for the secret values, so a Blueprint sync does not populate them for you.

## 7. Deploy
After the environment variables are saved:
1. Deploy the staging web service.
2. Deploy the staging worker.
3. Wait until both are healthy/running.

## 8. Verify in v0.5.1
Open a report and select **Report** in the left navigation.

The storage message should change from an R2 configuration warning to a configured state. This confirms the application sees syntactically valid settings. Then perform one real storage operation to verify credentials and bucket access, such as:
- upload a prospect logo;
- upload a small evidence file; or
- generate a controlled/stored publication after the report is Ready for review.

Draft Word/PDF downloads are intentionally independent of R2 and can be tested before or after this configuration.

## Troubleshooting
- **Invalid endpoint / placeholder error**: `S3_ENDPOINT` still contains placeholder text or is not a complete HTTPS URL.
- **Access denied**: verify Object Read & Write permission and bucket scope on the R2 token.
- **No such bucket**: verify `S3_BUCKET` exactly matches the Cloudflare bucket name.
- **Signature/authentication error**: verify Access Key ID, Secret Access Key, endpoint, and `S3_REGION=auto`.
- **Web works but publication fails**: verify the worker has the same R2 environment variables as the web service.
