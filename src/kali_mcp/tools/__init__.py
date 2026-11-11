"""Auto-import all tool modules to trigger registration.

The tool registry exposes the full inventory of tool wrappers so agents get
maximum capability. test_comprehensive.py's TOOL_ARGS map must include an
entry for every registered tool.
"""

from kali_mcp.tools.agent_interface import (
    AssessmentDiffTool,
    AssessmentRunTool,
    AssetGraphTool,
    BatchRunTool,
    CoverageSummaryTool,
    EvidenceGetTool,
    FindingsQueryTool,
    FindingTransitionTool,
    JobControlTool,
    ReportGenerateTool,
    ToolCatalogTool,
)
from kali_mcp.tools.amass import AmassTool
from kali_mcp.tools.arjun import ArjunTool
from kali_mcp.tools.bettercap import BettercapTool
from kali_mcp.tools.bloodhound import BloodhoundTool
from kali_mcp.tools.commix import CommixTool
from kali_mcp.tools.crackmapexec import CrackmapexecTool
from kali_mcp.tools.dirb import DirbTool
from kali_mcp.tools.dursgo import DursgoTool
from kali_mcp.tools.enum4linux import Enum4linuxTool

## Excluded: none — full tool inventory registered
from kali_mcp.tools.farsight import FarsightTool
from kali_mcp.tools.ffuf import FfufTool
from kali_mcp.tools.file_download import FileDownloadTool
from kali_mcp.tools.file_read import FileReadTool
from kali_mcp.tools.file_write import FileWriteTool
from kali_mcp.tools.flowlyt import FlowlytTool
from kali_mcp.tools.generic_command import GenericCommandTool
from kali_mcp.tools.gobuster import GobusterTool
from kali_mcp.tools.hashcat import HashcatTool
from kali_mcp.tools.httpx import HttpxTool
from kali_mcp.tools.hydra import HydraTool
from kali_mcp.tools.john import JohnTool
from kali_mcp.tools.katana import KatanaTool
from kali_mcp.tools.masscan import MasscanTool
from kali_mcp.tools.medusa import MedusaTool
from kali_mcp.tools.msfconsole import MsfconsoleTool
from kali_mcp.tools.naabu import NaabuTool
from kali_mcp.tools.netexec import NetexecTool
from kali_mcp.tools.nmap import NmapTool
from kali_mcp.tools.nuclei import NucleiTool
from kali_mcp.tools.parallel_execute import ParallelExecuteTool, ParallelStatusTool
from kali_mcp.tools.playbook_ad import PlaybookAdTool
from kali_mcp.tools.playbook_authoring import (
    PlaybookCreateTool,
    PlaybookPublishTool,
    PlaybookValidateTool,
)
from kali_mcp.tools.playbook_blackbox import (
    PlaybookCatalogTool,
    PlaybookResultTool,
    PlaybookRunTool,
)
from kali_mcp.tools.playbook_engine_tool import PlaybookEngineTool
from kali_mcp.tools.playbook_recon import PlaybookReconTool
from kali_mcp.tools.playbook_tools import PlaybookListTool, PlaybookStatusTool
from kali_mcp.tools.playbook_webapp import PlaybookWebappTool
from kali_mcp.tools.python_command import PythonCommandTool
from kali_mcp.tools.responder import ResponderTool
from kali_mcp.tools.searchsploit import SearchsploitTool
from kali_mcp.tools.spiderfoot import SpiderfootTool
from kali_mcp.tools.sqlmap import SqlmapTool
from kali_mcp.tools.subfinder import SubfinderTool
from kali_mcp.tools.template_tools import TemplateListTool, TemplateRunTool
from kali_mcp.tools.theharvester import TheharvesterTool
from kali_mcp.tools.vault_tool import (
    VaultDeleteTool,
    VaultListTool,
    VaultQueryTool,
    VaultReadTool,
    VaultStatsTool,
    VaultWriteTool,
)
from kali_mcp.tools.wfuzz import WfuzzTool
from kali_mcp.tools.whatweb import WhatwebTool
from kali_mcp.tools.wpscan import WpscanTool
from kali_mcp.tools.zap import ZapTool
from kali_mcp.tools.zighound import ZighoundTool
from kali_mcp.tools.zizmor import ZizmorTool

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
    VaultWriteTool(),
    VaultReadTool(),
    VaultQueryTool(),
    VaultListTool(),
    VaultDeleteTool(),
    VaultStatsTool(),
    FindingTransitionTool(),
    AssessmentDiffTool(),
    CoverageSummaryTool(),
    AssessmentRunTool(),
    BatchRunTool(),
    JobControlTool(),
    FindingsQueryTool(),
    EvidenceGetTool(),
    AssetGraphTool(),
    ToolCatalogTool(),
    ReportGenerateTool(),
    PlaybookRunTool(),
    PlaybookCatalogTool(),
    PlaybookResultTool(),
    PlaybookCreateTool(),
    PlaybookValidateTool(),
    PlaybookPublishTool(),
    TemplateListTool(),
    TemplateRunTool(),
]
