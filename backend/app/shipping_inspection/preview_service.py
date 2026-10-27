"""Small, private derivatives for viewing; original inspection evidence is immutable."""
from io import BytesIO
import logging

from fastapi import HTTPException
from fastapi.responses import Response
from PIL import Image, ImageOps

from app.core.storage import transfers

logger = logging.getLogger('commission')


def image_preview(key, record):
    """Called only after media authorization and releasing the database transaction."""
    try:
        with transfers.materialize('shipping-inspection', key, record) as path:
            with Image.open(path) as source:
                # JPEG can decode at reduced resolution. Bound other formats before
                # decoding, and never copy a full-size photo just to rotate it.
                source.draft('RGB', (1280, 1280))
                if source.width * source.height > 25_000_000:
                    raise ValueError('Image exceeds preview pixel budget')
                source.thumbnail((640, 640), Image.Resampling.LANCZOS)
                image = ImageOps.exif_transpose(source)
                if image.mode in ('RGBA', 'LA') or 'transparency' in image.info:
                    rgba = image.convert('RGBA')
                    image = Image.new('RGB', rgba.size, 'white')
                    image.paste(rgba, mask=rgba.getchannel('A'))
                else:
                    image = image.convert('RGB')
                output = BytesIO()
                image.save(output, 'JPEG', quality=75)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning('Inspection preview failed type=%s', type(exc).__name__)
        print(f'[shipping_inspection] preview failed type={type(exc).__name__}', flush=True)
        raise HTTPException(503, '照片预览暂时无法加载，请重试') from None
    return Response(output.getvalue(), media_type='image/jpeg', headers={'Cache-Control': 'private, no-store'})
