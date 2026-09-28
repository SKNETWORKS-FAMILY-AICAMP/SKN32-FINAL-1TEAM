from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


RENDERER = Path(
    r"C:\Users\playdata2\.codex\plugins\cache\openai-primary-runtime"
    r"\documents\26.904.11930\skills\documents\render_docx.py"
)
SOFFICE = r"C:\Program Files\LibreOffice\program\soffice.exe"

spec = spec_from_file_location("codex_render_docx", RENDERER)
module = module_from_spec(spec)
spec.loader.exec_module(module)
module._resolve_soffice = lambda: SOFFICE
module.main()
