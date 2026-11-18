from concurrent.futures import ThreadPoolExecutor

from app.factory_inbound import recognition_service

_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="factory-inbound-ocr")


def submit(note_id, attempt, original=False):
    _executor.submit(recognition_service.run, note_id, attempt, original)
