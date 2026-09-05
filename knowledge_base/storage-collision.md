# Proxy storage collision
Proxy and implementation contracts must agree on storage slot order. Adding or reordering variables can overwrite an owner or balance when delegatecalled. Use established proxy standards, reserved gaps, and upgrade layout checks.
