import sys
import pexpect

def run_pi(cmd, timeout=30):
    child = pexpect.spawn("ssh -o StrictHostKeyChecking=no pyken@minimix.local", timeout=timeout)
    idx = child.expect(["[Pp]assword:", pexpect.TIMEOUT, pexpect.EOF])
    if idx == 0:
        child.sendline("Oleole007")
    elif idx != 0:
        print("Failed to reach password prompt")
        return ""
    
    child.expect(r"pyken@minimix:.*\$ ")
    # Run command
    child.sendline(cmd)
    child.expect(r"pyken@minimix:.*\$ ")
    output = child.before.decode("utf-8", errors="ignore")
    # Clean up output
    lines = output.splitlines()
    if lines and cmd in lines[0]:
        lines = lines[1:]
    child.sendline("exit")
    child.close()
    return "\n".join(lines).strip()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = " ".join(sys.argv[1:])
        print(run_pi(cmd))
