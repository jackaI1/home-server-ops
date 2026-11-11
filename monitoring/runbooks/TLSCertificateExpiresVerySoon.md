# TLSCertificateExpiresVerySoon

**What it means:** the certificate for https://lifeos.jacklai.ca has less than 3 days left. Browsers will show a warning once it expires.

**Do this now**
1. Follow [TLSCertificateExpiresSoon](TLSCertificateExpiresSoon.md) to renew the certificate.
2. If renewal keeps failing, check that port 80 or 443 still reaches the server, since most certificate providers need it.
3. After renewing, confirm the expiry date moved forward in the "Days until TLS certificate expires" panel.
