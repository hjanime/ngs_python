# Import required modules
import pysam
import collections
import gzip
import multiprocessing
from ngs_analysis.system import iohandle
from general_functions import writeFile

def concordant(reads, maxSize):
    ''' Function to find concordant pairs. Input is a list/tuple
    that sequentially contains the chromosome, start, end and
    strand. Start is the most 5' base on the genome to which the
    read aligns. End is the most 3' base on the genome to which
    the read aligns.
    '''
    # Initialise return variable
    returnVariable = False
    # Only examine reads on same chromsomes and different strands
    if reads[0] == reads[4] and reads[3] != reads[7]:
        if reads[3] == '+':
            # Calculate and check read distance:
            distance = reads[6] - reads[1]
            if distance < maxSize:
                # Check that no read extends beyond its pair
                if (reads[5] >= reads[1] and
                    reads[6] >= reads[2]):
                    returnVariable = True
        elif reads[3] == '-':
            # Calculate and check read distance:
            distance = reads[2] - reads[5]
            if distance < maxSize:
                # Check that no read extends beyond its pair
                if (reads[2] >= reads[6] and
                    reads[1] >= reads[5]):
                    returnVariable = True
    # Retrun return variable
    return(returnVariable)

def processPairs(pipe, pairOut, rmDup, rmConcord, maxSize):
    ''' Function to output read pairs generated from the extract
    function while processing concordant and duplicate reads.
    Function takes five arguments:
    
    1)  readPairs - a read pair dictionary created by the extract
        function.
    2)  pairOut - output object which is processed by the
        iohandle.handleout function.
    3)  rmDup - Boolean indicating whether to remove duplicates
        from the output.
    4)  rmConcord - Boolean indicating whether to remove concordant
        pairs from the output.
    5)  alignLog - log dictionary generated by the extract
        function.
    
    Function returns two items:
    
    1)  A closed iohandle.handleout object
    2)  The altered alignLog from the input
    
    '''
    # Create counter and pair set
    pairCount = collections.defaultdict(int)
    pairSet = set()
    # Open output file process
    outObject = writeFile.writeFileProcess(fileName = pairOut)
    # Loop through pairs
    while True:
        # Get pair from pipe
        pair = pipe.recv()
        if pair == None:
            break
        # Count and check for duplicates pairs
        pairCount['total'] += 1
        if pair in pairSet:
            dup = True
            pairCount['duplicate'] += 1
        else:
            dup = False
            pairCount['unique'] += 1
            pairSet.add(pair)
        # Count and check for concordant pairs
        concord =  concordant(pair, maxSize)
        if concord:
            pairCount['concord'] += 1
            if not dup:
                pairCount['concorduni'] += 1
        else:
            pairCount['discord'] += 1
            if not dup:
                pairCount['discorduni'] += 1
        # Process output
        if dup and rmDup:
            continue
        elif concord and rmConcord:
            continue
        else:
            outData = '\t'.join(map(str,pair)) + '\n'
            outObject.add(outData)
    # Close file, return data and close pipe
    outObject.close()
    pipe.send(pairCount)
    pipe.close()

def extractPairs(inBam, pairOut, minMapQ, rmDup, rmConcord, maxSize):
    ''' Function to output read pairs generated from the extract
    function while processing concordant and duplicate reads.
    Function takes five arguments:
    
    1)  inBam - Path to input BAM file.
    2)  minMapQ - minimum mapping quality for a read to be
        processed,
    
    Function returns two items:
    
    1)  A python dictionary where the key is the read pair and the value
        is the frequency at which the read pair is found.
    2)  A python dictionary listing the alignment metrics.
    
    '''
    # Open bamfile
    bamFile = pysam.AlignmentFile(inBam, 'rb')
    # Generate dictionaries to store and process data
    alignCount = collections.defaultdict(int)
    strDict = {True: '-', False: '+'}
    chrDict = {}
    for r in bamFile.references:
        chrDict[bamFile.gettid(r)] = r
    # Initialise variables to store read data
    currentName = ""
    readList = []
    # Create process to handle pairs
    pipes = multiprocessing.Pipe(True)
    p = multiprocessing.Process(
        target = processPairs,
        args = (pipes[0], pairOut, rmDup, rmConcord, maxSize)
    )
    p.start()
    pipes[0].close()
    # Loop through BAM file
    while True:
        try:
            read = bamFile.next()
            readName = read.query_name
            alignCount['total'] += 1
        except StopIteration:
            readName = 'EndOfFile'
        # Process completed families
        if readName[:-2] != currentName[:-2]:
            # Count number of reads with identical ID
            readNo = len(readList)
            # Count and process properly mapped read-pairs
            if readNo == 2:
                # Unpack reads and check for read1 and read2
                read1, read2 = readList
                if (read1.query_name.endswith(':1') and 
                    read2.query_name.endswith(':2')):
                    # Count pairs and store data
                    output = (
                        chrDict[read1.reference_id],
                        read1.reference_start + 1,
                        read1.reference_end,
                        strDict[read1.is_reverse],
                        chrDict[read2.reference_id],
                        read2.reference_start + 1,
                        read2.reference_end,
                        strDict[read2.is_reverse],
                    )
                    pipes[1].send(output)
                    alignCount['pairs'] += 2
                # If not, count as multiple alignments
                else:
                    alignCount['multiple'] += 2
            # Count single mapped and multi mapped reads
            elif readNo == 1:
                alignCount['singletons'] += 1
            else:
                alignCount['multiple'] += readNo
            # Reset read list and current name
            currentName = readName
            readList = []
        # Break loop at end of BAM file
        if readName == 'EndOfFile':
            pipes[1].send(None)
            break
        # Count and skip secondary alignments
        elif (256 & read.flag):
            alignCount['secondary'] += 1
        # Count and skip umapped reads
        elif (4 & read.flag):
            alignCount['unmapped'] += 1
        # Count and skip poorly mapped reads
        elif read.mapping_quality < minMapQ:
            alignCount['poormap'] += 1
        # Process reads of sufficient quality
        else:
            readList.append(read)
    # Close BAM file
    bamFile.close()
    # Extract data from process and terminate
    pairCount = pipes[1].recv()
    pipes[1].close()
    p.join()
    # Output data
    return(alignCount, pairCount)
