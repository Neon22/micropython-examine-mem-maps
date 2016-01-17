#!/usr/bin/python

# Graphically show useful aspects of the .map file for micropython


### Specifically:
### Basic things to shown are:
###   - breakdown of section sizes (text/data/bss) per object file
###   - sorted, with sizes in bytes, percents, and as a D3 chart.
### Next direction of improvement is doing the same not per object file,
###  but per function.
### And another direction is taking 2 map files,
###  - one to be a reference (100%),
###  - and showing how each of pieces above change in the map file.
###  This diff mode is actually more useful (I think) than per-function stats


###-----------------------------------------
### .text is where program instructions are stored (FLASH)
### .data is where initialised static variables are stored (SRAM)
### .bss  is where uninitialised data is stored
###

### Blocks show the available memory blocks and map to devices e.g. RAM and Flash
### As usual Unix is different.


import sys
DEBUG = False # verbose printing switch

### map file sections (by examination)
# These are the sections in the .map file
SECTIONS = ["Preamble", # not a label. gather initial text
            "Allocating common symbols",    # Symbols, their size, file ref
            "Discarded input sections",     # ignoring for now
            "Memory Configuration",         # Blocks like RAM and Flash
            "Linker script and memory map", # mem map defined in here
               # mem map is .text, .rodata, .bss,  COMMON, .heap, .stack. .ARM
               # LOAD may appear in any order in this block
            "OUTPUT", #.comment, .ARM.attribute
            "Cross Reference Table"         # unix_only?
            ]

### export groups - ! limited for initial D3 version
CATS = ['.text', '.data',  '.rodata', '.heap','.stack', '.bss']
#CATS = ['.data',  '.rodata', '.heap','.stack', '.bss'] # text is BIG


## Classes
class Memory_map(object):
    """ Top level container for system.
        - Holds Blocks of regions etc...
    """
    def __init__(self, sysname, blocks=[]):
        self.system = sysname
        self.blocks = blocks
        self.output_loc = ""
    def __repr__(self):
        return "<Memmap %s %d blocks>" %(self.system, len(self.blocks))
    def describe(self):
        print self
        print " Output in", self.output_loc
        for b in self.blocks:
            b.describe(" ")
    
    def add_region(self, region):
        """ put region into proper Block based on addr, dur """
        addr = region.addr
        if addr:
            fail = True
            for b in self.blocks:
                if int(b.addr,16) <= int(addr,16) <= int(b.addr,16)+int(b.dur,16):
                    b.add_region(region)
                    fail = False
                    break # possibly *default* section which will get duplicates unless we break.
            if fail:
                print "!! failed to find Block for Region %s" % (region)
    def collect_region_names(self, region_names = []): 
        """ insert a block of reiogn names into eth growing list
            - use the existing list as the primary order
        """
        for b in self.blocks:
            ordered_insert(region_names, b.collect_region_names())
        return region_names

class Block(object):
    """ Representing a range of memory addresses.
        In embedded systems typically Flash, RAM, etc
        - an address, duration, name, attributes
        - holds the Regions referenced in that block of addresses
    """
    def __init__(self, addr, dur, name, attr):
        # all stored strings
        self.addr = addr 
        self.dur = dur
        self.name = name
        self.attr = attr
        self.regions = []  # hold regions that belong in address space of this block
    def __repr__(self):
        return "<Block %s %s (dur %s) %s %dregions>" % (self.addr, self.name, self.dur, self.attr, len(self.regions))
    def describe(self, preamble=""):
        print preamble,self
        for r in self.regions:
            r.describe(preamble+"     ")

    def address(self):
        " return as num, byte_count"
        return (int(self.addr, 0), (len(self.addr)-2)//2)
    def duration(self):
        " return as num, byte_count"
        return (int(self.dur, 0), (len(self.dur)-2)//2)
    def add_region(self, region):
        #print "Adding region", region
        self.regions.append(region)
        #self.regions.sort()
    def collect_region_names(self):
        """ return ordered list of region names """
        return  [r.fullname() for r in self.regions]


class Region(object):
    """ Regions contain a series of generally adjacent Symbols
        which belong in the same domain.
        - E.g. the Heap, or rodata.
    """
    def __init__(self, domain, name, addr, size):
        self.domain = domain
        self.name = name
        self.addr = addr
        self.size = size
        #
        self.load_addr = None
        self.align = None
        self.fill = None
        self.fill_with = None
        self.attr = []
        #
        self.symbols = [] # list of Symbols in increasing (mostly) addr order
    def __repr__(self):
        return "Region: %s[%s] addr=%s size=%s %d symbols" %(self.domain, self.name, self.addr, self.size, len(self.symbols))
    def fullname(self):
        return self.domain + (self.name if self.name else "")
    def describe(self, preamble=""):
        name = "Region: %s" % self.domain
        indent = "               " + preamble
        if self.name: name += self.name
        msg = preamble + name + " addr=%s size=%s" % (self.addr, self.size)
        if self.load_addr: msg+= " load_addr=%s" %(self.load_addr)
        msg += " %d symbols" % len(self.symbols)
        if self.fill or self.attr:
            msg+= "\n"
        if self.align: msg += indent +" align=%s" % self.align
        if self.fill:  msg += indent +" fill=%s" % self.fill
        if self.attr:
            for a in self.attr:
                msg += indent + " attr=%s\n" % a
            msg = msg[:-1]
        print msg

    def check_symbols(self):
        " ensure mem increasing and adjacent - report anomalies - probably not needed. "
        pass
    def equivalent(self, test_region):
        " Test to see if same region. Sometimes region in twice but has zero size "
        pass


class Linker_Load(object):
    """ Store filename for LOAD op
        - used by parse_linker_memmap
    """
    def __init__(self, filename):
        self.filename = filename
    def __repr__(self):
        return "<LOAD %s>" % (self.filename)

class Common_symbols(object):
    """ Hold all Common Symbols """
    def __init__(self, symbols=[]):
        self.symbols = symbols
    def __repr__(self):
        return "<Common_Symbols found %d>" %(len(self.symbols))
    
    def describe(self):
        for cs in self.symbols:
            print cs
    def add(self, symbol):
        self.symbols.append(symbol)
    
class Common_symbol(object):
    """ Some symbols have a domain=COMMON and this is a special type
        - store a symbol, size, originating file
    """
    def __init__(self, name, size, filename):
        self.name = name
        self.size = size
        self.filename = filename
        self.references = [] # filled in by linker sction when finding COMMON labels
    def __repr__(self):
        return "<Common_symbol %s size=%s from %s>" %(self.name, self.size, self.filename)


class Symbol(object):
    """ Many symbols can appear linked to the one address.
        - store the locations and lists of symbols and their attributes
    """
    def __init__(self, addr, size, primary, fill=None, fill_with=None ):
        self.addr = addr
        self.size = size
        self.file = None
        self.fill = fill
        self.fill_with = fill_with
        self.labels = [] # add new ones here (unique test as added ?)
        self.primary = primary # the LHS, also need to check in labels list for matches
        self.attributes = []
        
        # each entry is:
        #  sym_domain.label, addr, size, file
        # fill at end not always incrementing but always within size
        #  fill says what filled with(opt)
        # extra locations (within size) have one or more attributes(notes)
        # if domain=COMMON then point to Common_Symbol and vice versa
        # check label on RHS of second line and use if primary not the same (and not attr)
        # attributes are "load address", ".", PROVIDE
    def __repr__(self):
        return "<Symbol %s %s, %s>" %(self.primary, self.addr, self.size)
    def describe(self):
        msg = "Symbol: %s addr=%s, size=%s, file=%s" %(self.primary, self.addr, self.size, self.file)
        if self.fill: msg += " fill=%s with-%s" %(self.fill,self.fill_with)
        if self.labels: msg+= " %d labels" % len(self.labels)
        if self.attributes: msg+= " %d attributes" % len(self.attributes)
        return msg
    def stats(self):
        return self.addr, self.size, self.labels

###------------------------------------------
### Helper functions

def extract_system_name(name):
    """ look for handy system name in filename.
        - used to label top level memory map class
    """
    check = ["_","-","."]
    value = len(name)
    for char in check:
        pos = name.find(char)
        if pos > -1 and pos < value: value = pos
    return name[:value]

def extract_output_dir(name):
    """ remove OUTPUT and braces """
    name = name.strip()
    brace_pos = name.find("(")
    assert name[:brace_pos] == "OUTPUT"
    return name[brace_pos+1:-1]
    
def clean_blocks(blocks):
    """remove *default* block if supplied
    - encompassing and irrelevant
    """
    #return [b for b in blocks if b.name != "*default*"]
    # turns out we need for unix... typical :)
    return blocks

def create_regions(memmap, region_list):
    """ given a list of regions,
        - insert into the correct Blocks (based on address)
    """
    for r in region_list:
        memmap.add_region(r)

def ordered_insert(primary, newlist):
    """ for each item in newlist try to insert into primary in same order
    """
    print "inserting into list"
    print primary
    print newlist
    for idx in range(len(newlist)):
        item = newlist[idx]
        found_prioritem = found_postitem = prioritem = postitem = False
        if item not in primary:
            # insert it
            # find if prior item to idx is in primary
            if idx>0: 
                prioritem = newlist[idx-1]
                found_prioritem = primary.index(prioritem) if prioritem in primary else False
            # find if post item to idx is in primary
            if idx<len(newlist)-1: 
                postitem = newlist[idx+1]
                found_postitem = primary.index(postitem) if postitem in primary else False
            # if both then insert after prior
            # if one then insert after prior or before post
            #print primary, item, prioritem, postitem, found_prioritem, found_postitem
            if found_prioritem:
                primary.insert(found_prioritem+1, item)
            elif found_postitem:
                primary.insert(found_postitem, item)
            else: # append to end ?
                primary.append(item)
    return primary
    
def print_body(body):
    " to help with parsing a region "
    print "Examining", body[0][0],len(body)
    if len(body) < 12:
        for b in body: print "   ",b
    else:
        print "   ",body[0]
        if len(body)>2: print "   ",body[1]
        if len(body)>3: print "   ",body[2]
        if len(body)>4: print "   ",body[3]
        if len(body)>5: print "   ",body[4]
        if len(body)>6: print "    ..."
        for i in range(min(10, len(body)-5),0,-1):
            print "   ",body[-i]

#
def region_summary(regions):
    """ Specifically to prepare data for export into v1 csv style file
    """
    mem_use=[]
    returned_cats = []
    maxlen = 0
    for r in regions:
        mem_use.append([r.domain, r.addr, r.size])
        maxlen = max(maxlen, len(r.domain))
    print "Memory stats"
    for name,start,length in mem_use:
        start_dec = 0 if not start else int(start,0)//1024
        length_dec = 0
        if start:
            #print"length=", length,start,name
            if length:
                length_dec = int(length,0)//1024
                if length_dec: # 0 in kb so use bytes
                    length_dec = str(length_dec)+"kB"
                else: length_dec = str(int(length,0))+"B"
            else: # length = None # possibly directive
                length = length_dec = ""
        print "{0:{maxlen}} start={1:10} length={2:8} ({3:d}k,{4})".format(name,start,length,start_dec,length_dec, maxlen=maxlen)
        if name in CATS:
            # collect to save to file
            if length:
                returned_cats.append([name,length])
    return returned_cats






###---------------------------------------------------
def process_attr(region, attr):
    """ For Region attributes
        - could be a load address or an alignment adjustment
    """
    if attr[0] == 'load' and attr[1] == 'address':
        region.load_addr = attr[2]
    elif attr[0] == '.' and attr[2] == 'ALIGN':
        region.align = attr[-1]
    else:
        region.attr.append(attr)

def process_symbol(region, body, idx, name):
    """ Region is parsed. So new symbols in this region start with "."
        - may be split over lines (see refs for examples)
    """
    symbols = []
    in_symbol = True
    print len(body), idx
    for i in range(idx, idx+20):
        print body[i]
    print
    #
    while in_symbol:
        line = body[idx]
        print line
        syn_name = line[0]
        addr = line[1]
        size = line[2]
        sfile = line[3]
        symbol = Symbol(addr, size, syn_name)
        symbol.file = sfile
        idx += 1
        if idx > len(body):
            in_symbol = False
        else: # look ahead a line
            line = body[idx]
            if line[0][0] == ".": # starting new symbol
                in_symbol = False
                idx -= 1
                print "new sym - xit", line[0]
            else:
                # next line is same symbol if addr same
                if line[0] == addr:
                    # check label same esle add to labels
                    print " adding label", line[1:]
                    symbol.labels.append(line[1:])
                    idx += 1
                else: # new symbol
                    print "newsym", line
        print symbol.describe()
        
    #
    sys.exit()
    return symbols, idx


def process_region(body, verbose=DEBUG):
    """ Called by Parse region to extract region info
        - also then processes Symbols in that region
    """
    addr = size = attr = None
    #print_body(body)
    # Cleanup
    # -remove "*()"
    body = [b for b in body if b[0][:2] != "*("]
    # -get the addr, size on same line
    if not body[0][2] and len(body)>1:
        body[0][2] = body[1]
        del(body[ 1])
##    print_body(body)
    # name
    domain = body[0][0]
    name = body[0][1]
    # extract addr, size if there
##    if domain and domain.find('exception_ra') >-1:
##        print "###",body[0]
    if body[0][2]:
        if len(body[0][2]) == 2: # only addr, size
            addr,size = body[0][2]
        elif len(body[0][2]) > 2: # has attributes?
            addr = body[0][2][0]
            if body[0][2][1][:2] == "0x":
                size = body[0][2][1]
                attr = body[0][2][2:]
            else:
                attr = body[0][2][1:]
    region = Region(domain, name, addr, size)
    if attr:
        process_attr(region, attr) # add attr to region
    # consume lines staring with addresses
    if len(body) > 1:
        idx = 1
        while idx < len(body):
            val = body[idx][0]
            if val[:2] == '0x' and val == addr:
                # attribute
                process_attr(region, body[idx][1:]) # add attr to region
                # attribute or fill
            elif val == '*fill*' and body[idx][1] == addr:
                # add fill
                region.fill = body[idx][-1]
            elif val[0] == ".":
                # a symbol.
##                symbol,idx = process_symbol(region, body, idx, name)
##                region.symbols.append(symbol)
                pass
            # 
            idx += 1
    #
    if verbose:
        #print region
        region.describe()
    #
    #sys.exit()
    return region
    
    
def parse_sym_name(line):
    """ Extract domain and name from head of line
        - return domain and sym
        e.g. for ".rodata.pin_B6"
              domain = rodata, name = .pin_B6
    """
    line = line.strip().split()
    sym_name = None
    if line[0][1:].find(".") > 0:
        # found a dot separator
        sym = line[0][1:].split(".",1)
        sym_domain = line[0][0]+sym[0]
        if len(sym) > 1: sym_name = "."+sym[1]
    else:
        # no dot sep
        sym_domain = line[0]
    return sym_domain, sym_name


### Regions
def parse_region(section, idx):
    """ Called by parse_linker_memmap
        - parses entire region
    """
    done = False
    line = section[idx]
    sym_domain, sym_name = parse_sym_name(line)
    # maybe a long line or just label.
    line = line.split()
    if len(line) > 1:
        rest = line[1:]
    else:
        rest = None
    body = [[sym_domain, sym_name, rest]]
    # rest of lines
    idx += 1
    while not done:
        if idx >= len(section):
            done = True
        else:
            line = section[idx]
            #print line
            if line[0] !=" ": # end of region. exit
                done = True
                idx -= 1
                #print "end region", len(section) - idx, line
            else:
                data = line.split()
                body.append(data)
                #print "storing", data
        idx += 1
    #
    # Parse now into a structure
    body = process_region(body)
    return body,idx

###--------------------------------------------
### Parse each section

def parse_linker_memmap(section, verbose=DEBUG):
    """
    """
    # LOAD may come first, or mem layout
    loads = []  # store loaded files (linker)
    mems  = []  # store abs locations (memstart, heap etc)
    regions = []  # store each symbol from mem map
    print " Parsing Linker and Mem map"
    # might start with .label OR 0xvalue, OR LOAD
    symstart = False
    idx = 0 # line counter
    sym_addr = 0 # used to test if same symbol across lines
    sym_domain = sym_value = None
    sym_done = True
    while idx < len(section):
        s = section[idx] # iterate over lines in section
        line = s.split()
        #print "   ",line
        if line[0][0] == "." or line[0][0] == "/": # region start
            #print "\n.parsing region", line
            region,idx = parse_region(section, idx)
            regions.append(region)
            idx -= 1
            if verbose:
##                print "  Saved", region[0][0],len(region)
##                print "   ",region[0]
##                if len(region)>2: print "   ",region[1]
##                if len(region)>3: print "   ",region[2]
##                if len(region)>4: print "   ",region[3]
##                if len(region)>5: print "    ..."
##                for i in range(min(6, len(region)-4),0,-1):
##                    print "   ",region[-i]
                print region
        else:
            # could be LOAD or mem loc
            if line[0][:4] == 'LOAD':
                loads.append(Linker_Load(line[1]))
                #print "  LOAD", line
            elif line[0][:5] == 'START': #ignore groups
                pass
            elif line[0][:3] == 'END': #ignore groups
                pass
            else: # mem loc
##                if verbose:
##                    print "  mem loc:", line
                assert int(line[0], 0)
                mems.append(line)
        #
        idx += 1 
    # 
    if verbose:
        print "  Loads: %d found. E.g." % len(loads)
        for i in range(min(2, len(loads))): print "  ", loads[i]
        print "  Memory"
        for i in mems: print "  ",i
        print "  regions", len(regions)
        for i in regions: print "   ", i
        region_summary(regions)
    return regions


def parse_Output(section, verbose=DEBUG):
    """ Parse data in the "OUTPUT" section
        Expecting a filename.
        - contains .ARM attributes, comments, and debug symbols
        - all as regions
    """
    regions = [extract_output_dir(section[0][0])] # the output filename
    idx = 1 # skip firstline
    if verbose:
        print " Parsing Output section", len(section), "bytes long"
        print "  ", section[0][0]
    while idx < len(section):
        s = section[idx] # iterate over lines in section
        #print s
        line = s.split()
        if line[0][0] == ".": # start of new region
            region,idx = parse_region(section, idx)
            regions.append(region)
            idx -= 1
            if verbose:
                print region
##                # notneeded but helpful stopper
##                print "   Saved", len(region)
##                print "   ",region[0]
##                if len(region)>6: print "    ..."
##                for i in range(min(6, len(region)-1),0,-1):
##                    print "   ",region[-i]
        idx += 1
    #
    #print regions[0], len(regions)-1
    return regions


def parse_cross_refs(section, verbose=DEBUG):
    """ Parse data in the "Cross Reference Table" section
        Expecting a sequence of:
         - 'Symbol', 'File'
         - a symbol may have several files referenced.
        Return list of each Symbol_name followed by it's files
    """
    symbols = []
    print " Parsing Cross refs"
    first = True
    sym_name = False
    symbol = []
    for s in section:
        line = s.strip().split()
        if first: # first line is labels. verify
            assert line == ['Symbol', 'File']
            first = False
        else:
            # data lines
            #print len(line),line
            if len(line) == 1: # file to append
                #print "   ",symbol
                if symbol:
                    symbol.append(line[0])
                else:
                    print "Fail"
            else: # sym and file (len 2)
                assert len(line) == 2
                # save prev one
                if symbol:
                    symbols.append(symbol)
                symbol = line
                
    # do last one
    symbols.append(symbol)
    #
    if verbose:
        print "  Cross refs", len(symbols)
        print "   ",symbols[0]
        if len(symbols)>6: print "    ..."
        for i in range(min(6, len(symbols)-1),0,-1):
            print "   ",symbols[-i]
    return symbols
            

            
def parse_mem_config(section, verbose=DEBUG):
    """ Parse data in the "Memory Configuration" section
        Expecting a sequence of:
         - 'Name', 'Origin', 'Length', 'Attributes'
        Return list of Block classes
    """
    blocks = []
    print " Parsing Blocks"
    first = True
    for s in section:
        line = s.split()
        if first: # first line is labels. verify
            assert line == ['Name', 'Origin', 'Length', 'Attributes']
            first = False
        else:
            # data lines
            attr = None
            if len(line) == 4:
                attr = line[3]
            blocks.append(Block(line[1], line[2], line[0], attr))
    #
    if verbose:
        for b in blocks: print " ",b
    return blocks

        
def parse_common_symbols(section, verbose=DEBUG):
    """ The 'Allocating Common Symbols' block contains list of
        label, size, file
        Return list of Symbol classes
    """
    symbols = []
    print " Parsing Common Symbols"
    first = True
    done = True
    for s in section: # iterate over lines in section
        line = s.split()
        if first: # first line is labels. verify
            assert line == ['Common', 'symbol', 'size', 'file']
            first = False
        else:
            #print line, len(line), done
            if len(line) == 1:
                # rest is on nextline
                label = line[0]
                done = False
            elif not done:
                # cont of prev line
                assert len(line) == 2 # complete
                symbols.append(Common_symbol(label, line[0], line[1]))
                done = True
                label = ""
            else: # full line
                assert len(line) == 3
                symbols.append(Common_symbol(*line))
    #
    if verbose:
        for s in symbols: print " ",s
    return symbols


###-----------------------------------------------------
### Read the map file - gather into sections
def read_map_file(filename, verbose=DEBUG):
    """ Read the file into sections defined in SECTIONS
        - for parsing in sep pass.
        return as list of sections - of lines
    """
    sections = {}
    inf = open(filename, 'rU')
    lines = inf.readlines()
    print "%d lines read" % len(lines)
    inf.close()
    # start with preamble section (first in SECTIONS)
    section_count = 0
    label = SECTIONS[section_count]
    next_label = SECTIONS[section_count+1]
    size = len(next_label)
    section = []
    # proceed through all sections gathering lines
    for line in lines:
        stripped = line.rstrip() # leave leading space for grouping
        # Match the name in SECTIONS
        if stripped[:size] == next_label:
            # close section, move to next one
            sections[label] = section
            section_count += 1
            label = SECTIONS[section_count]
            # any more sections ?
            if section_count < len(SECTIONS)-1:
                next_label = SECTIONS[section_count+1]
                size = len(next_label)
            if label == 'OUTPUT': # special case this one
                # also grab title line
                section = [[stripped]]
            else:
                section = []
        else:
            # still in this section, keep gathering data
            if stripped:
                section.append(stripped)
    # gather the last one
    sections[label] = section
    #
    print "For: %s.\n  Found %d sections.\n %s\nReading:" %(filename, len(sections), sections.keys())
    if verbose:
        for label in SECTIONS:
            if sections.has_key(label):
                print " - %5d %s" % (len(sections[label]), label)
    return sections


def parse_sections(extracted, name):
    """ Step through each of the sections
        - calling the parser for each one
        - ignore Preamble Section
        - start with Blocks
        - load into the memorymap class
    """
    memmap = Memory_map(extract_system_name(name))
    blocks = parse_mem_config(extracted[SECTIONS[3]])   # Memory Configuration
    memmap.blocks = clean_blocks(blocks)
    #print memmap
    common_symbols = Common_symbols(parse_common_symbols(extracted[SECTIONS[1]])) # Common_Symbols
    common_symbols.describe()
    #  connect them - when pasing symbols ? !!
    mem_data = parse_linker_memmap(extracted[SECTIONS[4]])  # Regions of Symbols
    create_regions(memmap, mem_data) # insert into mem map
    #memmap.describe()
    outputs = parse_Output(extracted[SECTIONS[5]])  #
    memmap.output_loc = outputs[0]
    create_regions(memmap, outputs[1:])
    if extracted.has_key(SECTIONS[6]):
        cross_refs = parse_cross_refs(extracted[SECTIONS[6]]) # list of symbol names and ref_files
    return memmap

###-------------------------------------
### Exporting

# def collate_for(mem_map):
    # """ Turn the Memmap class into a dictionary for json exporting
    # """
    # mem_dict = pass
    


def export_categories(filename, returned_cats, verbose=True):
    """
    """
    if verbose: print "Summary"
    outf = open(filename, 'w')
    # title line
    outf.write("%s, " % "system")
    for c in CATS[:-1]: outf.write("%s, " %c)
    outf.write("%s\n" % CATS[-1])
    #for c in returned_cats: print c
    for system, sysname in zip(returned_cats, maps):
        outf.write("%s" % sysname[:sysname.find("_")])
        if verbose: print sysname
        for c in CATS:
            found = False
            for pair in system:
                if c in pair:
                    found = True
                    if pair[1]:
                        if verbose:
                            value = int(pair[1],0)
                        print "",c, pair, int(pair[1],0)
                    else:
                        value = 0
                        if verbose:
                            print "",c, pair, 0
                    outf.write(",%s" % (value))
            if not found:
                outf.write(",%s" % (0))
        outf.write('\n')
        if verbose: print
    outf.close()

def export_categories(filename, memmaps, regionlist):
    """ make CSV with on eline per mem_map of regions 
        - in regionlist order
    """
    print memmaps
    outf = open(filename, 'w')
    # title line
    outf.write("%s, " % "system")
    for name in regionlist[:-1]: outf.write("%s, " % name)
    outf.write("%s\n" % regionlist[-1])
    for m in memmaps:
        outf.write("%s" % m.system)
        # per mem_map
        regions = []
        for b in m.blocks: regions.extend(b.regions)
        data = [[r.fullname(), r.size] for r in regions]
        for name in regionlist:
            size = 0
            for f,s in data:
                if f==name:
                    size = int(s,16) if s else 0
                    break
            outf.write(",%s" % (size))
        outf.write('\n')
    outf.close()
        
    

###
if __name__ == "__main__":
    collected_maps = [] # for json export
    regionlist = CATS
    maps = ["teensy_micropython_dh_01.map",
            "unix_micropython_dh_01.map",
            "stmhal_firmware_dh_01.map",
            "microbit-micropython_01.map"]
    #maps = ["microbit-micropython_01.map"]
    for m in maps:
        extracted_data = read_map_file("mapfiles/"+m)
        print "Parsing:"
        mem_map = parse_sections(extracted_data, m)
        print "  mem"
        mem_map.describe()
        collected_maps.append(mem_map)
        # gather region info for v1 export
        regionlist = mem_map.collect_region_names(regionlist)
        #returned_cats.append(region_summary(mem_map[SECTIONS[4]]))
        #collected_maps[m.system] = collate_for_json(m)
        print
    #
    export_categories("mappings.csv",collected_maps, regionlist)

