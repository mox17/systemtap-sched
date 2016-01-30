#!/usr/bin/env python3
import sys
import argparse
import re

"""
Interpret systemtap logfile with scheduling information

@481:481>(RCC_HMI)    start process - parentheses indicate NAME of executable

#0>529                schedule to thread 529

0000000000111111111
0123456789012345678
[1313362665ns]@0:0>swapper/0
[1313381685ns]@1:1>init
[1313396535ns]@2:2>kthreadd
[1313411850ns]@3:3>ksoftirqd/0
[1313427045ns]@4:4>kworker/0:0
[1313442735ns]@5:5>kworker/0:0H
[1313458125ns]@6:6>kworker/u4:0
[
"""

class thread :
    def __init__(self, pid, tid, time, name, buckets):
        self.tid = tid
        self.start = time
        self.names = [name]
        self.buckets = [0 for i in range(buckets)]
        self.totalTime = 0  # Total CPU time in this thread
        return
        
    def scheduleIn(self, time, bucket):
        self.sliceStart = time
        self.bucket = bucket
        return
    
    def scheduleOut(self, time, btime, bucket):
        slice = 0
        if bucket != self.bucket:
            part1 = btime - self.sliceStart
            self.buckets[self.bucket] += part1
            self.sliceStart += part1
            slice += part1
        self.buckets[bucket] += time - self.sliceStart
        slice += time - self.sliceStart
        return slice

    def addName(self, name):
        if not name in self.names:
            self.names.append(name)
        return

class kernel :
    def __init__(self, bucketCount):
        self.processes = {}   # Map pid -> [tid]+
        self.threadName = {}  # Map tid -> name
        self.threads = {}     # Map tid -> thread
        self.tidpid = {}      # map tid -> pid
        self.pidtime = {}     # map pid -> cpu time
        self.bucketCount = bucketCount
        self.lastThread = None
        return

    def handleScheduling(self, pid, tid, time, btime, bucket):
        if self.lastThread:
            self.lastThread.scheduleOut(time, btime, bucket)
        return

    def processStart(self, pid, tid, time, btime, bucket, name):
        if not pid in self.processes:
            self.processes[pid] = [tid]
            self.pidtime[pid] = 0
            #print(time, pid, tid, name)
        else:
            if not tid in self.processes[pid]:
                self.processes[pid].append(tid)
                #print(time, pid, tid, self.processes[pid])
        if not tid in self.tidpid:
            self.tidpid[tid] = pid
        if not tid in self.threads:
            thr = thread(pid,tid,time,name,self.bucketCount)
            self.threads[tid] = thr
            self.threadName[tid] = name
        else:
            thr = self.threads[tid]
        if len(name) > 0:
            self.threadName[tid] = name
        self.handleScheduling(pid, tid, time, btime, bucket)
        thr.scheduleIn(time, bucket)
        self.lastThread = thr
        return
    
    def pidTime(self, tid, slice):
        self.pidtime[self.tidpid[tid]] += slice
        return
        
    def schedule(self, tid, time, btime, bucket):
        slice = self.lastThread.scheduleOut(time, btime, bucket)
        self.pidTime(tid, slice)
        self.lastThread = self.threads[tid]
        self.lastThread.scheduleIn(time, bucket)
        return

    def printProcesses(self, lastBucket, f = sys.stdout):
        k = self.processes.keys()
        for x in k:
            print('{:4d} {:12.9f} "{:s}"'.format(x, self.pidtime[x]/1000000000.0, self.threadName[x]), file=f)
        return
    
    def printTable(self, lastBucket, f = sys.stdout):
        # Create a list of processes ordred in descending orderby total cpu time
        k = self.processes.keys()
        pl = []
        for x in k:
            pl.append([x,self.pidtime[x],self.threadName[x]])
        p2 = sorted(pl, key=lambda rec: rec[1], reverse=True)
        # For each process print a list with cpu time used in each bucket
        for p in p2:
            timing = [0 for i in range(lastBucket+1)]
            threadList = self.processes[p[0]]
            for t in threadList:
                thr = self.threads[t]
                for bucket in range(lastBucket+1):
                    timing[bucket] += thr.buckets[bucket]/100000000.0
            # Output timing for process
            print('"{0}"'.format(p[2]),timing)
        return
    
#                               pid   tid   name
processPattern = re.compile(r'@(\d+):(\d+)>(.*)')
schedPattern   = re.compile(r'#(\d)>(\d+)')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("trek", help="systemtap/taptrek logfile")
    args = parser.parse_args()
    
    bucketCount = 2000
    bucketTime = 100000000 # 10^8 = 0.1s
    kern = kernel(bucketCount)
    
    with open(args.trek) as f:
        for line in f:
#            print(line)
            bracket = line.find(']')
            time = int(line[1:bracket-2])
            #ns = line[bracket-2:bracket]
            tenths = int(line[1:bracket-10])
            btime = time - (time % bucketTime)
            #print(time, btime, tenths)
            res = processPattern.search(line)
            if res != None:
                pid = int(res.group(1))
                tid = int(res.group(2))
                name = res.group(3)
                kern.processStart(pid, tid, time, btime, tenths, name)
            else:
                res = schedPattern.search(line)
                if res != None:
                    tid = int(res.group(2))
                    kern.schedule(tid, time, btime, tenths)
    #kern.printProcesses()
    kern.printTable(tenths)
    return

if __name__ == '__main__':
    main()