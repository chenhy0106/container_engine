from ast import parse
import subprocess
import os
import sys
import argparse

class Define:
    def __init__(self) -> None:
        self.IP_FILE = "/tmp/ip_addr.txt"
        self.BRIDGE_IP = "10.0.0.1/24"
        self.DEFAULT_BRIDGE_NAME = "Container_default_bridge"
        self.USE_DEFUALT_BRIDGE = "Default"
        self.NO_NET = "NULL"
        self.NETNSFILE = "/var/run/netns/"

D = Define()

def execCmd(cmds):
    for cmd in cmds:
        cmd_str = ""
        for c in cmd:
            cmd_str = cmd_str + str(c) + " "

        print(cmd_str)
        os.system(cmd_str)

        
def getID():
    if not os.path.exists(D.IP_FILE):
        execCmd([["touch ", D.IP_FILE]])

    infile = open(D.IP_FILE, "r")
    line = infile.readline()
    if line:
        next_valid = int(line)
    else:
        next_valid = 2

    next_valid = next_valid + 1
    outfile = open(D.IP_FILE, "w")
    outfile.write(str(next_valid))

    return next_valid - 1


def getIPaddr(Id):
    addr_str =  "10." + \
            str((Id >> 16) & 255) + "." + \
            str((Id >> 8) & 255) + "." + \
            str(Id & 255) + "/24"

    return addr_str



class Container:
    net_ns = ""
    ip = ""
    Id = 0
    pid = 0
    root_dir = ""

    @staticmethod
    def __create_bridge(bridgeName):
        res = os.popen("ip addr").readlines()

        new_name = True
        for line in res:
            if bridgeName in line:
                new_name = False
                break

        if new_name:
            create_bridge_cmd = ["ip link add", bridgeName, "type bridge"]
            set_bridge_ip = ["ip addr add", D.BRIDGE_IP, "dev", bridgeName]
            activate_bridge_cmd = ["ip link set dev", bridgeName, "up"]

            iptables_i = ["iptables", "-A", "FORWARD", "-i", bridgeName, "-j", "ACCEPT"]
            iptables_o = ["iptables", "-A",
                                    "FORWARD", "-o", bridgeName, "-j", "ACCEPT"]
            # 把物理eth也放入网桥，从而veth-pair可以ping通外网
            iptables_nat = ["iptables", "-t", "nat", "-A", "POSTROUTING",
                                  "-s", "10.0.1.0/24", "-o", "eth0", "-j", "MASQUERADE"]

            execCmd([create_bridge_cmd, set_bridge_ip, activate_bridge_cmd, iptables_i, iptables_o, iptables_nat])

    def __getStartCmd(self):
        cgroup_name = "Container_" + str(self.Id)
        cmd = ["cgexec"]
        cmd.append("-g")
        cmd.append("cpu,cpuset,memory:"+cgroup_name)
        cmd.append("unshare")
        
        cmd.append("--uts")
        cmd.append("--ipc")
        cmd.append("--user")
        cmd.append("--mount")
        cmd.append("--pid")
        cmd.append("--root")
        cmd.append(self.root_dir)
        cmd.append("--mount-proc")
        cmd.append("--net="+D.NETNSFILE+self.net_ns)
        cmd.append("--fork")
        cmd.append("/bin/bash")

        print(cmd)
        return cmd

    def __init(self, root_dir):
        self.Id = getID()
        self.ip = getIPaddr(self.Id)
        self.net_ns = "Container_" + str(self.Id)
        self.root_dir = root_dir

        res = os.popen("ip netns ls").readlines()
        new_netns = True
        for line in res:
            if self.net_ns in line:
                new_netns = False
                break

        create_netns = []
        if new_netns:
            create_netns = ["ip netns add", self.net_ns]

        execCmd([create_netns])

    def __configNetwork(self, bridgeName):
        self.__create_bridge(bridgeName)

        veth0 = self.net_ns + "_0"
        veth1 = self.net_ns + "_1"
        create_veth = ["ip link add", veth0, "type veth peer name", veth1]
        attach_veth0_on_netns = ["ip link set dev", veth0, "netns", self.net_ns]
        set_veth0_ip = ["ip netns exec", self.net_ns, "ip addr add", self.ip, "dev", veth0]
        activate_veth0 = ["ip netns exec", self.net_ns, "ip link set dev", veth0, "up"]
        activate_veth0_loop = ["ip netns exec", self.net_ns, "ip link set lo up"]

        set_veth1_ip = ["ip addr add", self.ip, "dev", veth1]
        attach_veth1_on_bridge = ["ip link set dev", veth1, "master", bridgeName]
        activate_veth1 = ["ip link set dev", veth1, "up"]

        set_gateway = ["ip", "netns", "exec", self.net_ns, "ip", "route", "add", "default", "via", D.BRIDGE_IP[:-3]]

        execCmd([create_veth, attach_veth0_on_netns, set_veth0_ip, activate_veth0, activate_veth0_loop, \
            set_veth1_ip, attach_veth1_on_bridge, activate_veth1, set_gateway])

    def __configpid(self, pid):
        self.pid = pid

    def __configUser(self, user_opt):
        newuid = "'0 " + str(user_opt[0]) + " 1'"
        newgid = "'0 " + str(user_opt[1]) + " 1'"
        uidfile = "> /proc/" + str(self.pid) + "/uid_map"
        gidfile = "> /proc/" + str(self.pid) + "/gid_map"
        set_uid = ["echo", newuid, uidfile]
        set_gid = ["echo", newgid, gidfile]

        execCmd([set_gid, set_uid])

    def __configMemory(self, mem_opt):
        # if mem_opt < 4096:
            # memory limit must be larger than 4096
            # mem_opt = 4096

        cgroup_name = "Container_" + str(self.Id)
        cgcreate = ["cgcreate", "-g", "memory:/"+cgroup_name]
        cgset = ["cgset", "-r", "memory.limit_in_bytes="+str(mem_opt), cgroup_name]
        cgclassify = ["cgclassify", "-g", "memory:"+cgroup_name, cgroup_name]

        execCmd([cgcreate, cgset])

    def __configCPU(self, cpu_opt):
        cpuset = cpu_opt[0]
        cpushare = str(cpu_opt[1])
        cpuset_str = "0"
        if cpuset > 1:
            cpuset_str = cpuset_str + "-" + str(cpuset-1)
        
        cgroup_name = "Container_" + str(self.Id)
        cgcreate_cpuset = ["cgcreate", "-g", "cpuset:/"+cgroup_name]
        cgset_cpuset_cpus = ["cgset", "-r", "cpuset.cpus="+cpuset_str, cgroup_name]
        cgset_cpuset_mems = ["cgset", "-r", "cpuset.mems=0", cgroup_name]
        cgclassify_cpuset = ["cgclassify", "-g", "cpuset:"+cgroup_name, cgroup_name]
        cgcreate_cpu = ["cgcreate", "-g", "cpu:/"+cgroup_name]
        cgset_cpu_cpushare = ["cgset", "-r", "cpu.shares="+cpushare, cgroup_name]
        cgclassify_cpu = ["cgclassify", "-g", "cpu:"+cgroup_name, cgroup_name]

        execCmd([cgcreate_cpuset, cgset_cpuset_cpus, cgset_cpuset_mems, \
            cgcreate_cpu, cgset_cpu_cpushare])

    def __chowner(self):
            chown_to_root = ["chown", "-R", "root:root", self.root_dir]
            execCmd([chown_to_root])

    def __destory(self):
        # destory net
        veth1 = self.net_ns + "_1"
        destory_veth1 = ["ip link delete", veth1]
        # destory_netns = ["ip netns delete"]

        #destory cgroup
        cgroup_name = "Container_" + str(self.Id)
        cgdelete_mem = ["cgdelete", "memory:"+cgroup_name]
        cgdelete_cpu = ["cgdelete", "cpu:"+cgroup_name]
        cgdelete_cpuset = ["cgdelete", "cpuset:"+cgroup_name]

        execCmd([destory_veth1, cgdelete_mem, cgdelete_cpu, cgdelete_cpuset])

    def run(self, net_opt, root_dir, user_opt, mem_opt, cpu_opt):

        self.__init(root_dir)
        self.__configMemory(mem_opt)
        self.__configCPU(cpu_opt)

        sub = subprocess.Popen(self.__getStartCmd())
        print("container ID : " + str(self.Id) + ", IP : " + str(self.ip))
        
        self.__configpid(sub.pid)
        self.__configNetwork(net_opt)
        self.__configUser(user_opt)
        self.__chowner()
        
        sub.wait()

        self.__destory()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-r", "--root", type=str, dest="rootDir", default="")
    parser.add_argument("-n", "--net", type=str, dest="net_opt", default="Default")
    parser.add_argument("-m", "--memory", type=str, dest="mem_opt", default="1M")
    parser.add_argument("-u", "--uid", type=int, dest="uid", default=0)
    parser.add_argument("-g", "--gid", type=int, dest="gid", default=0)
    parser.add_argument("--cpus", type=int, dest="cpus", default=1)
    parser.add_argument("--cpu-share", type=int, dest="cpushare", default=256)
    args = parser.parse_args()

    container = Container()

    container.run(  net_opt=args.net_opt, \
                    root_dir=args.rootDir, \
                    user_opt=(args.uid, args.gid), \
                    mem_opt=args.mem_opt, \
                    cpu_opt=(args.cpus, args.cpushare))
