# TLSCertificateExpiresSoon

**What it means:** the certificate that lets browsers trust https://lifeos.jacklai.ca has less than 14 days left.

**Check first**
1. Open the site and view the certificate, or run `echo | openssl s_client -connect lifeos.jacklai.ca:443 -servername lifeos.jacklai.ca 2>/dev/null | openssl x509 -noout -enddate`.
2. Check the "Days until TLS certificate expires" panel on the dashboard.

**Fix**
- If the certificate provider renews automatically, check that the renewal job ran. If it failed, read its log, fix the cause and run the renewal again.
- If renewal is manual, renew now. The alert clears once the new certificate is served.
