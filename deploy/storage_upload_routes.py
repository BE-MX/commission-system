"""Per-endpoint gateway budgets, preserving each site's business owner."""

# One MiB of multipart overhead beyond the corresponding business limit.
LIMITS = [
    (r'/api/assets/(upload|[0-9]+/version)', 501),
    (r'/api/customer-media/batches/[0-9]+/assets', 501),
    (r'/api/training/[0-9]+/files', 301),
    (r'/api/aftersales/cases/[0-9]+/evidence', 201),
    (r'/api/pm/materials/[0-9]+/versions', 51),
    (r'/api/(assets/tag-image-upload|design/requests/[0-9]+/attachments|domestic/images|aftersales/sop/versions|customer-image/products/[0-9]+/(assets|references)/upload|customer-image/public/logo)', 21),
    (r'/api/expo/(sessions|scenes/[^/]+/image|upload/[^/]+|wigs/upload-photo|hair-colors/upload-swatch|beautify-prompt-versions/[0-9]+/preview)', 21),
    (r'/api/(knowledge/libraries/[0-9]+/assets|card/admin/attachments)', 11),
    (r'/api/insight/cases/upload', 6),
]


def snippet(region):
    if region not in {'cloud', 'cloud-ip', 'office'}:
        return ''
    port = 8002 if region == 'office' else 8001
    blocks = []
    for pattern, limit in LIMITS:
        blocks.append(f'''location ~ ^{pattern}$ {{
    client_max_body_size {limit}m;
    client_body_timeout 300s;
    proxy_pass http://127.0.0.1:{port};
    proxy_set_header Host $host;
    proxy_set_header Authorization $http_authorization;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_http_version 1.1;
    proxy_request_buffering off;
    proxy_buffering off;
    proxy_cache off;
    proxy_next_upstream off;
    proxy_connect_timeout 10s;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
}}''')
    return '\n'.join(blocks)
