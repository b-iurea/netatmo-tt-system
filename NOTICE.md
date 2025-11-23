This project includes a modified version of the open-source software
"netatmo_api" originally written by redcorjo and distributed under the
GNU General Public License v3.0 (GPL-3.0).

Original repository:
  https://github.com/redcorjo/netatmo_api

Modifications performed by b-iurea (2025):
  - Added an HTTP endpoint `/health` to expose a simple liveliness check.
  - Removed some unnecessary `int()` conversions in Netatmo API handlers.
  - Minor adjustments to improve container readiness and integration in Kubernetes-based environments.

These modifications are redistributed under the same license (GPL-3.0)
as required by the original work.

You can obtain a full copy of the modified source code at:
  https://github.com/<tuo-username>/<nome-repo-modificata>
  
The LICENSE file in this directory provides the complete terms of the
GNU General Public License v3.0.
