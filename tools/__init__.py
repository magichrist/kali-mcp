"""Auto-import all tool modules to trigger registration.

The tool registry exposes the full inventory of tool wrappers so agents get
maximum capability. test_comprehensive.py's TOOL_ARGS map must include an
entry for every registered tool.
"""

from tools.amass import AmassTool
from tools.arjun import ArjunTool
from tools.bettercap import BettercapTool
from tools.bloodhound import BloodhoundTool
from tools.commix import CommixTool
from tools.crackmapexec import CrackmapexecTool
from tools.dirb import DirbTool
from tools.dursgo import DursgoTool
from tools.enum4linux import Enum4linuxTool

## Excluded: none — full tool inventory registered
from tools.farsight import FarsightTool
from tools.ffuf import FfufTool
from tools.file_download import FileDownloadTool
from tools.file_read import FileReadTool
from tools.file_write import FileWriteTool
from tools.flowlyt import FlowlytTool
from tools.generic_command import GenericCommandTool
from tools.gobuster import GobusterTool
from tools.hashcat import HashcatTool
from tools.httpx import HttpxTool
from tools.hydra import HydraTool
from tools.john import JohnTool
from tools.katana import KatanaTool
from tools.masscan import MasscanTool
from tools.medusa import MedusaTool
from tools.msfconsole import MsfconsoleTool
from tools.naabu import NaabuTool
from tools.netexec import NetexecTool
from tools.nmap import NmapTool
from tools.nuclei import NucleiTool
from tools.parallel_execute import ParallelExecuteTool, ParallelStatusTool
from tools.playbook_ad import PlaybookAdTool
from tools.playbook_engine_tool import PlaybookEngineTool
from tools.playbook_recon import PlaybookReconTool
from tools.playbook_tools import PlaybookListTool, PlaybookStatusTool
from tools.playbook_webapp import PlaybookWebappTool
from tools.python_command import PythonCommandTool
from tools.responder import ResponderTool
from tools.searchsploit import SearchsploitTool
from tools.spiderfoot import SpiderfootTool
from tools.sqlmap import SqlmapTool
from tools.subfinder import SubfinderTool
from tools.theharvester import TheharvesterTool
from tools.wfuzz import WfuzzTool
from tools.whatweb import WhatwebTool
from tools.wpscan import WpscanTool
from tools.zap import ZapTool
from tools.zighound import ZighoundTool
from tools.zizmor import ZizmorTool

# Ordered list of tool instances (full inventory)
ALL_TOOLS = [
    GenericCommandTool(),
    PythonCommandTool(),
    FileReadTool(),
    FileWriteTool(),
    FileDownloadTool(),
    NmapTool(),
    HttpxTool(),
    NucleiTool(),
    FfufTool(),
    KatanaTool(),
    SubfinderTool(),
    AmassTool(),
    SqlmapTool(),
    CommixTool(),
    WpscanTool(),
    Enum4linuxTool(),
    NetexecTool(),
    CrackmapexecTool(),
    BloodhoundTool(),
    TheharvesterTool(),
    SpiderfootTool(),
    NaabuTool(),
    ArjunTool(),
    WhatwebTool(),
    DursgoTool(),
    FlowlytTool(),
    SearchsploitTool(),
    ZighoundTool(),
    ZizmorTool(),
    FarsightTool(),
    MsfconsoleTool(),
    HydraTool(),
    HashcatTool(),
    GobusterTool(),
    MasscanTool(),
    JohnTool(),
    ZapTool(),
    WfuzzTool(),
    DirbTool(),
    MedusaTool(),
    BettercapTool(),
    ResponderTool(),
    ParallelExecuteTool(),
    ParallelStatusTool(),
    PlaybookReconTool(),
    PlaybookWebappTool(),
    PlaybookAdTool(),
    PlaybookEngineTool(),
    PlaybookListTool(),
    PlaybookStatusTool(),
]
