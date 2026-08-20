# Staging Deployment — v0.5.1

1. Download the v0.5.1 source ZIP and PowerShell launcher into the Windows Downloads folder.
2. Run `Apply_Collaborative_Capture_R2_v0.5.1_From_Downloads.ps1`.
3. The installer moves release artifacts to `CloudInventoryDiscovery\installers\v0.5.1-collaborative-capture-r2`.
4. It requires a clean local repository, fetches GitHub, verifies `origin/staging` is v0.5.0, and creates `feature/collaborative-capture-r2-v0.5.1` from the current staging commit.
5. It applies the packaged source, detects Windows LibreOffice, and runs the complete staging validation.
6. Only after validation succeeds does it commit and push the feature branch.
7. With `-PromoteToStaging`, it fast-forwards and pushes `staging`.
8. Configure Cloudflare R2 values on both Render staging web and worker services before testing persistent storage/final publication.
9. In Render, Sync Blueprint if required for version/config metadata, then deploy the latest staging commit for both web and worker.
