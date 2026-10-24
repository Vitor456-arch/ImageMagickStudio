import sys
import os
import tempfile
import uuid
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root),str(root/'vendor')]
temporary=root/'.test-work'
temporary.mkdir(exist_ok=True)
os.environ['TEMP']=os.environ['TMP']=str(temporary)
tempfile.tempdir=str(temporary)
import pytest
raise SystemExit(pytest.main([str(root/'tests'),'-q','--basetemp',str(temporary/uuid.uuid4().hex),*sys.argv[1:]]))
