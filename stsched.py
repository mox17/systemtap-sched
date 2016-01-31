#!/usr/bin/env python3
import sys
import argparse
import re

"""
Interpret systemtap logfile with scheduling information

@481:481>(RCC_HMI)    start process/thread  (pid:tid)
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
        self.buckets = [0 for i in range(buckets+1)]
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
        if bucket-self.bucket > 1:
            print("Bucket skip", bucket, self.bucket, time, btime, file=sys.stderr)
            #assert(bucket-self.bucket <= 1) # assume scheduling happens more than once per bucketTime
            
        self.buckets[bucket] += time - self.sliceStart
        slice += time - self.sliceStart
        return slice

    def addName(self, name):
        if not name in self.names:
            self.names.append(name)
        return

class kernel :
    def __init__(self, cores, bucketCount, bucketTime, processCount):
        self.cores = cores    #
        self.processes = {}   # Map pid -> [tid]+
        self.threadName = {}  # Map tid -> name
        self.threads = {}     # Map tid -> thread
        self.tidpid = {}      # map tid -> pid
        self.pidtime = {}     # map pid -> cpu time
        self.bucketCount = bucketCount   # Max number of buckets to process
        self.bucketTime = bucketTime     # Time interval per bucket in ns
        self.lastThread = [None for i in range(self.cores)] # Previously executing thread in relevant core(object)
        self.processCount = processCount # How many processes to graph (with rest summarized under misc)
        return

    def handleScheduling(self, core, pid, tid, time, btime, bucket):
        if self.lastThread[core]:
            self.lastThread[core].scheduleOut(time, btime, bucket)
        return

    def processStart(self, pid, tid, time, btime, bucket, name):
        if not pid in self.processes:
            # A new process was created
            self.processes[pid] = [tid] # So far it has its own thread
            self.pidtime[pid] = 0       # And no CPU time spent yet
        else:
            # A thread was added to an existing process
            if not tid in self.processes[pid]:
                self.processes[pid].append(tid)
        if not tid in self.tidpid:
            # Mapping frok threads to processes
            self.tidpid[tid] = pid
        if not tid in self.threads:
            thr = thread(pid,tid,time,name,self.bucketCount)
            self.threads[tid] = thr
        else:
            thr = self.threads[tid]
        if len(name) > 0:
            self.threadName[tid] = name
        # No scheduling yet - we don't know which core
        #self.handleScheduling(pid, tid, time, btime, bucket)
        #thr.scheduleIn(time, bucket)
        #self.lastThread = thr
        return
    
    def pidTime(self, tid, slice):
        self.pidtime[self.tidpid[tid]] += slice
        return
        
    def schedule(self, core, tid, time, btime, bucket):
        if self.lastThread[core] != None:
            slice = self.lastThread[core].scheduleOut(time, btime, bucket)
            self.pidTime(self.lastThread[core].tid, slice) # Accumulate time for process which just ran
        self.lastThread[core] = self.threads[tid]
        self.lastThread[core].scheduleIn(time, bucket)
        return

    def printProcesses(self, lastBucket, f):
        k = self.processes.keys()
        print("name,cpu,pid",file=f)
        for x in k:
            print('"{2:s}",{1:12.9f},{0:5d}'.format(x, self.pidtime[x]/1E9, self.threadName[x]), file=f)
        return
    
    def printTable(self, lastBucket, f=sys.stdout):
        maxProcessCount = self.processCount
        # Create a list of processes ordred in descending orderby total cpu time
        k = self.processes.keys()
        pl = []
        for x in k:
            if x != 0:
                # Skip tid 0 (swapper) which is idle time
                pl.append([x,self.pidtime[x],self.threadName[x]])
        p2 = sorted(pl, key=lambda rec: rec[1], reverse=True)

        # First row is "Time(s)","Process0","Process1"..."Process99","Misc"
        processCount = len(p2)
        titleRow = ['"Time(s)"']
        for p in p2[:min(maxProcessCount, processCount)]:
            titleRow.append('"{0}"'.format(self.threadName[p[0]]))
        if processCount > maxProcessCount:
            titleRow.append("Misc")

        # Create an array to hold a column of data for time, each process [and misc]
        dataRow = [None for i in range(min(maxProcessCount, processCount)+2)]

        # Create column of start times
        timeColumn = [0 for i in range(lastBucket+1)]
        for bucket in range(lastBucket):
            timeColumn[bucket] = bucket * self.bucketTime
        dataRow[0] = timeColumn
        
        # Create a column of data for each of the maxProcessCount most active processes
        idx = 1
        for p in p2[:min(processCount, maxProcessCount)]:
            timing = [0 for i in range(lastBucket+1)]
            threadList = self.processes[p[0]]
            for t in threadList:
                thr = self.threads[t]
                for bucket in range(lastBucket+1):
                    timing[bucket] += thr.buckets[bucket]/self.bucketTime
            dataRow[idx] = timing
            idx += 1

        # Summarize data for processes beyond the maxProcessCount most active
        if processCount > maxProcessCount:
            # An empty array for the sum
            summarize = [0 for i in range(lastBucket+1)]
            for p in p2[maxProcessCount:]:
                threadList = self.processes[p[0]]
                for t in threadList:
                    thr = self.threads[t]
                    for bucket in range(lastBucket+1):
                        summarize[bucket] += thr.buckets[bucket]/self.bucketTime
            dataRow[idx] = summarize
            idx += 1
            
        # Time to output data
        for t in titleRow:
            print("{0},".format(t),end='',file=f)
        print(file=f)
        for i in range(lastBucket):
            print("{:11.9f},".format(dataRow[0][i]/1.0E9),end='',file=f)
            for x in range(1,idx):
                #print(x,idx,i,maxProcessCount,processCount,file=sys.stderr)
                print("{:11.9f},".format(dataRow[x][i]),end='',file=f)
            print(file=f)
        return

    def mergeProcessesWithSameNames(self):
        nameDict = {}       # Map name to process pid
        processKeys = self.processes.keys() # Get list of pid's
        removeList = []
        for p in processKeys:
            processName = self.threadName[p]
            if not processName in nameDict:
                nameDict[processName] = p
            else:
                # Name already seen, move list of tid's to earlier found thread
                pid = nameDict[processName]
                self.processes[pid] = self.processes[pid] + self.processes[p]
                # Handle accumulated time
                self.pidtime[pid] += self.pidtime[p]
                # Handle mapping from tid back to pid
                for t in self.processes[p]:     
                    self.tidpid[t] = pid
                #del self.processes[p]
                removeList.append(p)
                #print("Merging process {0} {1}".format(p, processName),file=sys.stderr)
        for p in removeList:
            del self.processes[p]
        return

# Regular expressions for analyzing trek files    
#                               pid   tid   name
processPattern = re.compile(r'@(\d+):(\d+)>(.*)')
#                              core  tid
schedPattern   = re.compile(r'#(\d)>(\d+)')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("trek", help="systemtap/taptrek logfile")
    parser.add_argument("--bucket", type=int, help="Length of sampling bucket in ns", default=100000000)
    parser.add_argument("--duration", type=float, help="Skip data beyond 'duration' seconds")
    parser.add_argument("--pcount", type=int, help="Number of ranked processes to display", default=100)
    parser.add_argument("--merge", help="Merge processes with same name", action='store_true')
    parser.add_argument("--summary", help="File with summary of CPU seconds per process")
    parser.add_argument("--output", help="File with CPU distribution over time")
    parser.add_argument("--cores", type=int, help="Number of processor cores", default=8)
    args = parser.parse_args()
    
    bucketTime = float(args.bucket) #100000000.0 # 10^8 = 0.1s
    if args.duration:
        bucketCount = int((args.duration * 1E9 / bucketTime)+1)
        durationNs = (args.duration * 1E9) + bucketTime
    else:
        bucketCount = 20000 # some arbitrary  number
        durationNs = 0      # No cutoff, process to end of file
    kern = kernel(args.cores, bucketCount, bucketTime, args.pcount)
    
    with open(args.trek) as f:
        for line in f:
            bracket = line.find(']')
            time = int(line[1:bracket-2]) # timestamp in ns
            if durationNs and (time > durationNs):
                break
            # Calculate which discrete time interval we are in now
            bucketIdx = int(time / bucketTime)
            # Time for beginning of this interval
            btime = time - (time % bucketTime)
            res = processPattern.search(line)
            if res != None:
                pid = int(res.group(1))
                tid = int(res.group(2))
                name = res.group(3)
                kern.processStart(pid, tid, time, btime, bucketIdx, name)
            else:
                res = schedPattern.search(line)
                if res != None:
                    core = int(res.group(1))
                    tid = int(res.group(2))
                    kern.schedule(core, tid, time, btime, bucketIdx)
    # Log file processed, now process data and generate output
    if args.merge:
        kern.mergeProcessesWithSameNames()
    if args.summary:
        print("Writing summary to '{0}'".format(args.summary),file=sys.stderr)
        sum = open(args.summary,"wt")
        kern.printProcesses(bucketIdx, sum)
        sum.close()
    if args.output:
        print("Writing output to '{0}'".format(args.output),file=sys.stderr)
        output = open(args.output,"wt")
        kern.printTable(bucketIdx,output)
        output.close()
    else:
        kern.printTable(bucketIdx)
    return

if __name__ == '__main__':
    main()