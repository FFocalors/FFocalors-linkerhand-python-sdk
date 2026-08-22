from pathlib import Path


script_path = Path(__file__).with_name("prepare_full_report.py")
source = script_path.read_text(encoding="utf-8")
source = source.replace('## 三、总体架构设计")', "## 三、总体架构设计''')")
namespace = {"__name__": "report_prepare_module", "__file__": str(script_path)}
exec(compile(source, str(script_path), "exec"), namespace)
namespace["build_docx"]()
