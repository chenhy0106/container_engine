import subprocess
import os
import sys

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

def getOpt(net_ns):
    cmd = ["unshare"]
# unshare_cmd = ["unshare", "--uts", --net=" + D.NETNSFILE + self.net_ns + " --ipc --user --mount --pid --mount-proc --fork /bin/bash"
        
    cmd.append("--uts")
    cmd.append("--ipc")
    cmd.append("--user")
    cmd.append("--mount")
    cmd.append("--pid")
    cmd.append("--map-root-user")
    cmd.append("--root")
    cmd.append("centos")
    cmd.append("--mount-proc")
    cmd.append("--net="+D.NETNSFILE+net_ns)
    cmd.append("--fork")
    cmd.append("/bin/bash")
    return cmd



class Container:
    net_ns = ""
    ip = ""
    Id = 0
    pid = 0

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

            execCmd([create_bridge_cmd, set_bridge_ip, activate_bridge_cmd])

    def __init(self):
        self.Id = getID()
        self.ip = getIPaddr(self.Id)
        self.net_ns = "Container_" + str(self.Id)

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

        execCmd([create_veth, attach_veth0_on_netns, set_veth0_ip, activate_veth0, activate_veth0_loop, \
            set_veth1_ip, attach_veth1_on_bridge, activate_veth1])

    def __setpid(self, pid):
        self.pid = pid

    def __configUser(self, user_opt):
        newuid = "'0 " + str(user_opt[0]) + " 1'"
        newgid = "'0 " + str(user_opt[1]) + " 1'"
        uidfile = "> /proc/" + str(self.pid) + "/uid_map"
        gidfile = "> /proc/" + str(self.pid) + "/gid_map"
        set_uid = ["echo", newuid, uidfile]
        set_gid = ["echo", newgid, gidfile]

        execCmd([set_gid, set_uid])

    def __destory(self):
        veth1 = self.net_ns + "_1"
        destory_veth1 = ["ip link delete", veth1]

        # destory_netns = ["ip netns delete"]
        execCmd([destory_veth1])

    def run(self, net_opt, user_opt):
        self.__init()

        sub = subprocess.Popen(getOpt(self.net_ns))
        print("container ID : " + str(self.Id) + ", IP : " + str(self.ip))
        
        self.__setpid(sub.pid)
        self.__configNetwork(net_opt)
        # self.__configUser(user_opt)
        
        sub.wait()

        self.__destory()

if __name__ == "__main__":
    container = Container()

    container.run(net_opt="Default", user_opt=(1000, 1000))
