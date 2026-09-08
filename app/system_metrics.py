import os,time
from pathlib import Path
class MetricsSampler:
    def __init__(self):self.previous=None
    def sample(self):
        result={"process_memory_mb":None,"process_cpu_percent":None,"system_load_1m":None,"cpu_temperature_c":None,"available_memory_mb":None,"system_uptime_seconds":None}
        try:result["system_load_1m"]=round(os.getloadavg()[0],2)
        except (OSError,AttributeError):pass
        try:
            line=next(x for x in Path("/proc/self/status").read_text().splitlines() if x.startswith("VmRSS:"))
            result["process_memory_mb"]=round(float(line.split()[1])/1024,1)
        except (OSError,StopIteration,ValueError):pass
        try:
            line=next(x for x in Path("/proc/meminfo").read_text().splitlines() if x.startswith("MemAvailable:"));result["available_memory_mb"]=round(float(line.split()[1])/1024,1)
        except (OSError,StopIteration,ValueError):pass
        try:result["system_uptime_seconds"]=round(float(Path("/proc/uptime").read_text().split()[0]))
        except (OSError,ValueError,IndexError):pass
        try:
            ticks=os.sysconf("SC_CLK_TCK");fields=Path("/proc/self/stat").read_text().split();cpu=(int(fields[13])+int(fields[14]))/ticks;now=time.monotonic()
            if self.previous:
                wall=now-self.previous[0];result["process_cpu_percent"]=round(max(0,(cpu-self.previous[1])/wall*100),1) if wall else None
            self.previous=(now,cpu)
        except (OSError,ValueError,IndexError):pass
        try:result["cpu_temperature_c"]=round(float(Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip())/1000,1)
        except (OSError,ValueError):pass
        return result
def load_is_high(settings):
    if not settings.load_shedding_enabled:return False
    try:return os.getloadavg()[0]>settings.load_shedding_threshold
    except (OSError,AttributeError):return False
