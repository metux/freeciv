#!/usr/bin/env python

#
# Freeciv - Copyright (C) 2003 - Raimar Falke
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation; either version 2, or (at your option)
#   any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#

### The following parameters change the amount of output.

# generate_stats will generate a large amount of statistics how many
# info packets got discarded and how often a field is transmitted. You
# have to call delta_stats_report to get these.
generate_stats=0

# generate_logs will generate log calls to debug the delta code.
generate_logs=1
use_log_macro="log_packet_detailed"
generate_variant_logs=1

### The following parameters CHANGE the protocol. You have been warned.
fold_bool_into_header=1
disable_delta=0

################# END OF PARAMETERS ####################

# This program runs under python 1.5 and 2.2 and hopefully every
# version in between. Please leave it so. In particular use the string
# module and not the function of the string type.

import re, string, os, sys

lazy_overwrite=0

def verbose(s):
    if len(sys.argv)>1 and sys.argv[1]=="-v":
        print(s)
        
def prefix(prefix,str):
    lines=str.split("\n")
    lines=map(lambda x,prefix=prefix: prefix+x,lines)
    return "\n".join(lines)

def write_disclaimer(f):
    f.write('''
 /****************************************************************************
 *                       THIS FILE WAS GENERATED                             *
 * Script: common/generate_packets.py                                        *
 * Input:  common/packets.def                                                *
 *                       DO NOT CHANGE THIS FILE                             *
 ****************************************************************************/

''')

def my_open(name):
    verbose("writing %s"%name)
    f=open(name,"w")
    write_disclaimer(f)
    return f

def get_choices(all):
    def helper(helper,all, index, so_far):
        if index>=len(all):
            return [so_far]
        t0=so_far[:]
        t1=so_far[:]
        t1.append(list(all)[index])
        return helper(helper,all,index+1,t1)+helper(helper,all,index+1,t0)

    result=helper(helper,all,0,[])
    assert len(result)==2**len(all)
    return result

def without(all,part):
    result=[]
    for i in all:
        if i not in part:
            result.append(i)
    return result
    
# A simple container for a type alias
class Type:
    def __init__(self,alias,dest):
        self.alias=alias
        self.dest=dest

# Parses a line of the form "COORD x, y; key" and returns a list of
# Field objects. types is a list of Type objects which are used to
# dereference type names.
def parse_fields(str, types):
    mo=re.search(r"^\s*(\S+(?:\(.*\))?)\s+([^;()]*)\s*;\s*(.*)\s*$",str)
    assert mo,str
    arr=[]
    for i in mo.groups():
        if i:
            arr.append(i.strip())
        else:
            arr.append("")
    type,fields_,flags=arr
    #print arr

    # analyze type
    while 1:
        found=0
        for i in types:
            if i.alias==type:
                type=i.dest
                found=1
                break
        if not found:
            break

    typeinfo={}
    mo=re.search("^(.*)\((.*)\)$",type)
    assert mo,repr(type)
    typeinfo["dataio_type"],typeinfo["struct_type"]=mo.groups()

    if typeinfo["struct_type"]=="float":
        mo=re.search("^(\D+)(\d+)$",typeinfo["dataio_type"])
        assert mo
        typeinfo["dataio_type"]=mo.group(1)
        typeinfo["float_factor"]=int(mo.group(2))

    # analyze fields
    fields=[]
    for i in fields_.split(","):
        i=i.strip()
        t={}

        def f(x):
            arr=x.split(":")
            if len(arr)==1:
                return [x,x,x]
            else:
                assert len(arr)==2
                arr.append("old->"+arr[1])
                arr[1]="real_packet->"+arr[1]
                return arr

        mo=re.search(r"^(.*)\[(.*)\]\[(.*)\]$",i)
        if mo:
            t["name"]=mo.group(1)
            t["is_array"]=2
            t["array_size1_d"],t["array_size1_u"],t["array_size1_o"]=f(mo.group(2))
            t["array_size2_d"],t["array_size2_u"],t["array_size2_o"]=f(mo.group(3))
        else:
            mo=re.search(r"^(.*)\[(.*)\]$",i)
            if mo:
                t["name"]=mo.group(1)
                t["is_array"]=1
                t["array_size_d"],t["array_size_u"],t["array_size_o"]=f(mo.group(2))
            else:
                t["name"]=i
                t["is_array"]=0
        fields.append(t)

    # analyze flags
    flaginfo={}
    arr=list(item.strip() for item in flags.split(","))
    arr=list(filter(lambda x:len(x)>0,arr))
    flaginfo["is_key"]=("key" in arr)
    if flaginfo["is_key"]: arr.remove("key")
    flaginfo["diff"]=("diff" in arr)
    if flaginfo["diff"]: arr.remove("diff")
    if disable_delta:
        flaginfo["diff"] = 0
    adds=[]
    removes=[]
    remaining=[]
    for i in arr:
        mo=re.search("^add-cap\((.*)\)$",i)
        if mo:
            adds.append(mo.group(1))
            continue
        mo=re.search("^remove-cap\((.*)\)$",i)
        if mo:
            removes.append(mo.group(1))
            continue
        remaining.append(i)
    arr=remaining
    assert len(arr)==0,repr(arr)
    assert len(adds)+len(removes) in [0,1]

    if adds:
        flaginfo["add_cap"]=adds[0]
    else:
        flaginfo["add_cap"]=""

    if removes:
        flaginfo["remove_cap"]=removes[0]
    else:
        flaginfo["remove_cap"]=""

    #print typeinfo,flaginfo,fields
    result=[]
    for f in fields:
        result.append(Field(f,typeinfo,flaginfo))
    return result

# Class for a field (part of a packet). It has a name, serveral types,
# flags and some other attributes.
class Field:
    def __init__(self,fieldinfo,typeinfo,flaginfo):
        for i in fieldinfo,typeinfo,flaginfo:
            self.__dict__.update(i)
        self.is_struct=not not re.search("^struct.*",self.struct_type)

    # Helper function for the dictionary variant of the % operator
    # ("%(name)s"%dict).
    def get_dict(self,vars):
        result=self.__dict__.copy()
        result.update(vars)
        return result

    def get_handle_type(self):
        if self.dataio_type=="string":
            return "const char *"
        if self.dataio_type=="worklist":
            return "const %s *"%self.struct_type
        if self.is_array:
            return "const %s *"%self.struct_type
        return self.struct_type+" "

    # Returns code which is used in the declaration of the field in
    # the packet struct.
    def get_declar(self):
        if self.is_array==2:
            return "%(struct_type)s %(name)s[%(array_size1_d)s][%(array_size2_d)s]"%self.__dict__
        if self.is_array:
            return "%(struct_type)s %(name)s[%(array_size_d)s]"%self.__dict__
        else:
            return "%(struct_type)s %(name)s"%self.__dict__

    # Returns code which copies the arguments of the direct send
    # functions in the packet struct.
    def get_fill(self):
        if self.dataio_type=="worklist":
            return "  worklist_copy(&real_packet->%(name)s, %(name)s);"%self.__dict__
        if self.is_array==0:
            return "  real_packet->%(name)s = %(name)s;"%self.__dict__
        if self.dataio_type=="string":
            return "  sz_strlcpy(real_packet->%(name)s, %(name)s);"%self.__dict__
        if self.is_array==1:
            tmp="real_packet->%(name)s[i] = %(name)s[i]"%self.__dict__
            return '''  {
    int i;

    for (i = 0; i < %(array_size_u) s; i++) {
      %(tmp)s;
    }
  }'''%self.get_dict(vars())
        
        return repr(self.__dict__)

    # Returns code which sets "differ" by comparing the field
    # instances of "old" and "readl_packet".
    def get_cmp(self):
        if self.dataio_type=="memory":
            return "  differ = (memcmp(old->%(name)s, real_packet->%(name)s, %(array_size_d)s) != 0);"%self.__dict__
        if self.dataio_type=="bitvector":
            return "  differ = !BV_ARE_EQUAL(old->%(name)s, real_packet->%(name)s);"%self.__dict__
        if self.dataio_type in ["string","bit_string"] and self.is_array==1:
            return "  differ = (strcmp(old->%(name)s, real_packet->%(name)s) != 0);"%self.__dict__
        if self.is_struct and self.is_array==0:
            return "  differ = !are_%(dataio_type)ss_equal(&old->%(name)s, &real_packet->%(name)s);"%self.__dict__
        if not self.is_array:
            return "  differ = (old->%(name)s != real_packet->%(name)s);"%self.__dict__
        
        if self.dataio_type=="string":
            c="strcmp(old->%(name)s[i], real_packet->%(name)s[i]) != 0"%self.__dict__
            array_size_u=self.array_size1_u
            array_size_o=self.array_size1_o
        elif self.is_struct:
            c="!are_%(dataio_type)ss_equal(&old->%(name)s[i], &real_packet->%(name)s[i])"%self.__dict__
        else:
            c="old->%(name)s[i] != real_packet->%(name)s[i]"%self.__dict__

        return '''
    {
      differ = (%(array_size_o)s != %(array_size_u)s);
      if(!differ) {
        int i;
        for (i = 0; i < %(array_size_u)s; i++) {
          if (%(c)s) {
            differ = TRUE;
            break;
          }
        }
      }
    }'''%self.get_dict(vars())

    # Returns a code fragment which updates the bit of the this field
    # in the "fields" bitvector. The bit is either a "content-differs"
    # bit or (for bools which gets folded in the header) the actual
    # value of the bool.
    def get_cmp_wrapper(self,i):
        cmp=self.get_cmp()
        if fold_bool_into_header and self.struct_type=="bool" and \
           not self.is_array:
            b="packet->%(name)s"%self.get_dict(vars())
            return '''%s
  if(differ) {
    different++;
  }
  if (%s) {
    BV_SET(fields, %d);
  }

'''%(cmp,b,i)
        else:
            return '''%s
  if (differ) {
    different++;
    BV_SET(fields, %d);
  }

'''%(cmp,i)

    # Returns a code fragment which will put this field if the
    # content has changed. Does nothing for bools-in-header.    
    def get_put_wrapper(self,packet,i):
        if fold_bool_into_header and self.struct_type=="bool" and \
           not self.is_array:
            return "  /* field %(i)d is folded into the header */\n"%vars()
        put=self.get_put()
        packet_name=packet.name
        log_macro=packet.log_macro
        if packet.gen_log:
            f='    %(log_macro)s("  field \'%(name)s\' has changed");\n'%self.get_dict(vars())
        else:
            f=""
        if packet.gen_stats:
            s='    stats_%(packet_name)s_counters[%(i)d]++;\n'%self.get_dict(vars())
        else:
            s=""
        return '''  if (BV_ISSET(fields, %(i)d)) {
%(f)s%(s)s  %(put)s
  }
'''%self.get_dict(vars())

    # Returns code which put this field.
    def get_put(self):
        if self.dataio_type=="bitvector":
            return "DIO_BV_PUT(&dout, packet->%(name)s);"%self.__dict__

        if self.struct_type=="float" and not self.is_array:
            return "  dio_put_%(dataio_type)s(&dout, real_packet->%(name)s, %(float_factor)d);"%self.__dict__
        
        if self.dataio_type in ["worklist"]:
            return "  dio_put_%(dataio_type)s(&dout, &real_packet->%(name)s);"%self.__dict__

        if self.dataio_type in ["memory"]:
            return "  dio_put_%(dataio_type)s(&dout, &real_packet->%(name)s, %(array_size_u)s);"%self.__dict__
        
        arr_types=["string","bit_string","city_map","tech_list",
                   "unit_list","building_list"]
        if (self.dataio_type in arr_types and self.is_array==1) or \
           (self.dataio_type not in arr_types and self.is_array==0):
            return "  dio_put_%(dataio_type)s(&dout, real_packet->%(name)s);"%self.__dict__
        if self.is_struct:
            if self.is_array==2:
                c="dio_put_%(dataio_type)s(&dout, &real_packet->%(name)s[i][j]);"%self.__dict__
            else:
                c="dio_put_%(dataio_type)s(&dout, &real_packet->%(name)s[i]);"%self.__dict__
        elif self.dataio_type=="string":
            c="dio_put_%(dataio_type)s(&dout, real_packet->%(name)s[i]);"%self.__dict__
            array_size_u=self.array_size1_u

        elif self.struct_type=="float":
            if self.is_array==2:
                c="  dio_put_%(dataio_type)s(&dout, real_packet->%(name)s[i][j], %(float_factor)d);"%self.__dict__
            else:
                c="  dio_put_%(dataio_type)s(&dout, real_packet->%(name)s[i], %(float_factor)d);"%self.__dict__
        else:
            if self.is_array==2:
                c="dio_put_%(dataio_type)s(&dout, real_packet->%(name)s[i][j]);"%self.__dict__
            else:
                c="dio_put_%(dataio_type)s(&dout, real_packet->%(name)s[i]);"%self.__dict__

        if not self.diff:
            if self.is_array==2 and self.dataio_type!="string":
                return '''
    {
      int i, j;

      for (i = 0; i < %(array_size1_u)s; i++) {
        for (j = 0; j < %(array_size2_u)s; j++) {
          %(c)s
        }
      }
    } '''%self.get_dict(vars())
            else:
                return '''
    {
      int i;

      for (i = 0; i < %(array_size_u)s; i++) {
        %(c)s
      }
    } '''%self.get_dict(vars())
        else:
            return '''
    {
      int i;

      fc_assert(%(array_size_u)s < 255);

      for (i = 0; i < %(array_size_u)s; i++) {
        if(old->%(name)s[i] != real_packet->%(name)s[i]) {
          dio_put_uint8(&dout, i);
          %(c)s
        }
      }
      dio_put_uint8(&dout, 255);
    } '''%self.get_dict(vars())

    # Returns a code fragment which will get the field if the
    # "fields" bitvector says so.
    def get_get_wrapper(self,packet,i):
        get=self.get_get()
        if fold_bool_into_header and self.struct_type=="bool" and \
           not self.is_array:
            return  "  real_packet->%(name)s = BV_ISSET(fields, %(i)d);\n"%self.get_dict(vars())
        get=prefix("    ",get)
        log_macro=packet.log_macro
        if packet.gen_log:
            f="    %(log_macro)s(\"  got field '%(name)s'\");\n"%self.get_dict(vars())
        else:
            f=""
        return '''  if (BV_ISSET(fields, %(i)d)) {
%(f)s%(get)s
  }
'''%self.get_dict(vars())

    # Returns code which get this field.
    def get_get(self):
        if self.struct_type=="float" and not self.is_array:
            return '''if (!dio_get_%(dataio_type)s(&din, &real_packet->%(name)s, %(float_factor)d)) {
  RECEIVE_PACKET_FIELD_ERROR(%(name)s);
}'''%self.__dict__
        if self.dataio_type=="bitvector":
            return '''if (!DIO_BV_GET(&din, real_packet->%(name)s)) {
  RECEIVE_PACKET_FIELD_ERROR(%(name)s);
}'''%self.__dict__
        if self.dataio_type in ["string","bit_string","city_map"] and \
           self.is_array!=2:
            return '''if (!dio_get_%(dataio_type)s(&din, real_packet->%(name)s, sizeof(real_packet->%(name)s))) {
  RECEIVE_PACKET_FIELD_ERROR(%(name)s);
}'''%self.__dict__
        if self.is_struct and self.is_array==0:
            return '''if (!dio_get_%(dataio_type)s(&din, &real_packet->%(name)s)) {
  RECEIVE_PACKET_FIELD_ERROR(%(name)s);
}'''%self.__dict__
        if self.dataio_type in ["tech_list","unit_list","building_list"]:
            return '''if (!dio_get_%(dataio_type)s(&din, real_packet->%(name)s)) {
  RECEIVE_PACKET_FIELD_ERROR(%(name)s);
}'''%self.__dict__
        if not self.is_array:
            if self.struct_type in ["int","bool"]:
                return '''if (!dio_get_%(dataio_type)s(&din, &real_packet->%(name)s)) {
  RECEIVE_PACKET_FIELD_ERROR(%(name)s);
}'''%self.__dict__
            else:
                return '''{
  int readin;
  
  if (!dio_get_%(dataio_type)s(&din, &readin)) {
    RECEIVE_PACKET_FIELD_ERROR(%(name)s);
  }
  real_packet->%(name)s = readin;
}'''%self.__dict__

        if self.is_struct:
            if self.is_array==2:
                c='''if (!dio_get_%(dataio_type)s(&din, &real_packet->%(name)s[i][j])) {
      RECEIVE_PACKET_FIELD_ERROR(%(name)s);
    }'''%self.__dict__
            else:
                c='''if (!dio_get_%(dataio_type)s(&din, &real_packet->%(name)s[i])) {
      RECEIVE_PACKET_FIELD_ERROR(%(name)s);
    }'''%self.__dict__
        elif self.dataio_type=="string":
            c='''if (!dio_get_%(dataio_type)s(&din, real_packet->%(name)s[i], sizeof(real_packet->%(name)s[i]))) {
      RECEIVE_PACKET_FIELD_ERROR(%(name)s);
    }'''%self.__dict__
        elif self.struct_type=="float":
            if self.is_array==2:
                c='''if (!dio_get_%(dataio_type)s(&din, &real_packet->%(name)s[i][j], %(float_factor)d)) {
      RECEIVE_PACKET_FIELD_ERROR(%(name)s);
    }'''%self.__dict__
            else:
                c='''if (!dio_get_%(dataio_type)s(&din, &real_packet->%(name)s[i], %(float_factor)d)) {
      RECEIVE_PACKET_FIELD_ERROR(%(name)s);
    }'''%self.__dict__
        elif self.is_array==2:
            if self.struct_type in ["int","bool"]:
                c='''if (!dio_get_%(dataio_type)s(&din, &real_packet->%(name)s[i][j])) {
      RECEIVE_PACKET_FIELD_ERROR(%(name)s);
    }'''%self.__dict__
            else:
                c='''{
      int readin;
  
      if (!dio_get_%(dataio_type)s(&din, &readin)) {
        RECEIVE_PACKET_FIELD_ERROR(%(name)s);
      }
      real_packet->%(name)s[i][j] = readin;
    }'''%self.__dict__
        elif self.struct_type in ["int","bool"]:
            c='''if (!dio_get_%(dataio_type)s(&din, &real_packet->%(name)s[i])) {
      RECEIVE_PACKET_FIELD_ERROR(%(name)s);
    }'''%self.__dict__
        else:
            c='''{
      int readin;
  
      if (!dio_get_%(dataio_type)s(&din, &readin)) {
        RECEIVE_PACKET_FIELD_ERROR(%(name)s);
      }
      real_packet->%(name)s[i] = readin;
    }'''%self.__dict__

        if self.is_array==2:
            array_size_u=self.array_size1_u
            array_size_d=self.array_size1_d
        else:
            array_size_u=self.array_size_u
            array_size_d=self.array_size_d

        if not self.diff or self.dataio_type=="memory":
            if array_size_u != array_size_d:
                extra='''
  if (%(array_size_u)s > %(array_size_d)s) {
    RECEIVE_PACKET_FIELD_ERROR(%(name)s, ": truncation array");
  }'''%self.get_dict(vars())
            else:
                extra=""
            if self.dataio_type=="memory":
                return '''%(extra)s
  if (!dio_get_%(dataio_type)s(&din, real_packet->%(name)s, %(array_size_u)s)){
    RECEIVE_PACKET_FIELD_ERROR(%(name)s);
  }'''%self.get_dict(vars())
            elif self.is_array==2 and self.dataio_type!="string":
                return '''
{
  int i, j;
%(extra)s
  for (i = 0; i < %(array_size1_u)s; i++) {
    for (j = 0; j < %(array_size2_u)s; j++) {
      %(c)s
    }
  }
}'''%self.get_dict(vars())
            else:
                return '''
{
  int i;
%(extra)s
  for (i = 0; i < %(array_size_u)s; i++) {
    %(c)s
  }
}'''%self.get_dict(vars())
        else:
            return '''
for (;;) {
  int i;

  if (!dio_get_uint8(&din, &i)) {
    RECEIVE_PACKET_FIELD_ERROR(%(name)s);
  }
  if (i == 255) {
    break;
  }
  if (i > %(array_size_u)s) {
    RECEIVE_PACKET_FIELD_ERROR(%(name)s,
                               \": unexpected value %%%%d \"
                               \"(> %(array_size_u)s) in array diff\",
                               i);
  } else {
    %(c)s
  }
}'''%self.get_dict(vars())

#'''

# Class which represents a capability variant.
class Variant:
    def __init__(self,poscaps,negcaps,name,fields,packet,no):
        self.log_macro=use_log_macro
        self.gen_stats=generate_stats
        self.gen_log=generate_logs
        self.name=name
        self.packet_name=packet.name
        self.fields=fields
        self.no=no
        
        self.no_packet=packet.no_packet
        self.want_post_recv=packet.want_post_recv
        self.want_pre_send=packet.want_pre_send
        self.want_post_send=packet.want_post_send
        self.type=packet.type
        self.delta=packet.delta
        self.is_info=packet.is_info
        self.cancel=packet.cancel
        self.want_force=packet.want_force

        self.poscaps=poscaps
        self.negcaps=negcaps
        if self.poscaps or self.negcaps:
            def f(cap):
                return '(has_capability("%s", pc->capability) && has_capability("%s", our_capability))'%(cap,cap)
            t=(list(map(lambda x,f=f: f(x),self.poscaps))+
               list(map(lambda x,f=f: '!'+f(x),self.negcaps)))
            self.condition=" && ".join(t)
        else:
            self.condition="TRUE"
        self.key_fields=list(filter(lambda x:x.is_key,self.fields))
        self.other_fields=list(filter(lambda x:not x.is_key,self.fields))
        self.bits=len(self.other_fields)
        self.keys_format=", ".join(["%d"]*len(self.key_fields))
        self.keys_arg=", ".join(map(lambda x:"real_packet->"+x.name,
                                      self.key_fields))
        if self.keys_arg:
            self.keys_arg=",\n    "+self.keys_arg

        if len(self.fields)==0:
            self.delta=0
            self.no_packet=1

        if len(self.fields)>5 or self.name.split("_")[1]=="ruleset":
            self.handle_via_packet=1

        self.extra_send_args=""
        self.extra_send_args2=""
        self.extra_send_args3=", ".join(
            map(lambda x:"%s%s"%(x.get_handle_type(), x.name),
                self.fields))
        if self.extra_send_args3:
            self.extra_send_args3=", "+self.extra_send_args3

        if not self.no_packet:
            self.extra_send_args=', const struct %(packet_name)s *packet'%self.__dict__+self.extra_send_args
            self.extra_send_args2=', packet'+self.extra_send_args2

        if self.want_force:
            self.extra_send_args=self.extra_send_args+', bool force_to_send'
            self.extra_send_args2=self.extra_send_args2+', force_to_send'
            self.extra_send_args3=self.extra_send_args3+', bool force_to_send'

        self.receive_prototype='static struct %(packet_name)s *receive_%(name)s(struct connection *pc)'%self.__dict__
        self.send_prototype='static int send_%(name)s(struct connection *pc%(extra_send_args)s)'%self.__dict__

    # See Field.get_dict
    def get_dict(self,vars):
        result=self.__dict__.copy()
        result.update(vars)
        return result

    # Returns a code fragment which contains the declarations of the
    # statistical counters of this packet.
    def get_stats(self):
        names=map(lambda x:'"'+x.name+'"',self.other_fields)
        names=", ".join(names)

        return '''static int stats_%(name)s_sent;
static int stats_%(name)s_discarded;
static int stats_%(name)s_counters[%(bits)d];
static char *stats_%(name)s_names[] = {%(names)s};

'''%self.get_dict(vars())

    # Returns a code fragment which declares the packet specific
    # bitvector. Each bit in this bitvector represents one non-key
    # field.    
    def get_bitvector(self):
        return "BV_DEFINE(%(name)s_fields, %(bits)d);\n\n"%self.__dict__

    # Returns a code fragment which is the packet specific part of
    # the delta_stats_report() function.
    def get_report_part(self):
        return '''
  if (stats_%(name)s_sent > 0 &&
      stats_%(name)s_discarded != stats_%(name)s_sent) {
    log_test(\"%(name)s %%d out of %%d got discarded\",
      stats_%(name)s_discarded, stats_%(name)s_sent);
    for (i = 0; i < %(bits)d; i++) {
      if(stats_%(name)s_counters[i] > 0) {
        log_test(\"  %%4d / %%4d: %%2d = %%s\",
          stats_%(name)s_counters[i],
          (stats_%(name)s_sent - stats_%(name)s_discarded),
          i, stats_%(name)s_names[i]);
      }
    }
  }
'''%self.__dict__

    # Returns a code fragment which is the packet specific part of
    # the delta_stats_reset() function.
    def get_reset_part(self):
        return '''
  stats_%(name)s_sent = 0;
  stats_%(name)s_discarded = 0;
  memset(stats_%(name)s_counters, 0,
         sizeof(stats_%(name)s_counters));
'''%self.__dict__

    # Returns a code fragment which is the implementation of the hash
    # function. The hash function is using all key fields.
    def get_hash(self):
        if len(self.key_fields)==0:
            return "#define hash_%(name)s hash_const\n\n"%self.__dict__
        else:
            intro='''static genhash_val_t hash_%(name)s(const void *vkey)
{
'''%self.__dict__

            body='''  const struct %(packet_name)s *key = (const struct %(packet_name)s *) vkey;

'''%self.__dict__

            keys=list(map(lambda x:"key->"+x.name,self.key_fields))
            if len(keys)==1:
                a=keys[0]
            elif len(keys)==2:
                a="(%s << 8) ^ %s"%(keys[0], keys[1])
            else:
                assert 0
            body=body+('  return %s;\n'%a)
            extro="}\n\n"
            return intro+body+extro

    # Returns a code fragment which is the implementation of the cmp
    # function. The cmp function is using all key fields. The cmp
    # function is used for the hash table.    
    def get_cmp(self):
        if len(self.key_fields)==0:
            return "#define cmp_%(name)s cmp_const\n\n"%self.__dict__
        else:
            intro='''static bool cmp_%(name)s(const void *vkey1, const void *vkey2)
{
'''%self.__dict__
            body=""
            body=body+'''  const struct %(packet_name)s *key1 = (const struct %(packet_name)s *) vkey1;
  const struct %(packet_name)s *key2 = (const struct %(packet_name)s *) vkey2;

'''%self.__dict__
            for field in self.key_fields:
                body=body+'''  return key1->%s == key2->%s;
'''%(field.name,field.name)
            extro="}\n\n"
            return intro+body+extro

    # Returns a code fragment which is the implementation of the send
    # function. This is one of the two real functions. So it is rather
    # complex to create.
    def get_send(self):
        temp='''%(send_prototype)s
{
<real_packet1><delta_header>  SEND_PACKET_START(%(type)s);
<log><report><pre1><body><pre2><post>  SEND_PACKET_END(%(type)s);
}

'''
        if self.gen_stats:
            report='''
  stats_total_sent++;
  stats_%(name)s_sent++;
'''
        else:
            report=""
        if self.gen_log:
            log='\n  %(log_macro)s("%(name)s: sending info about (%(keys_format)s)"%(keys_arg)s);\n'
        else:
            log=""
        if self.want_pre_send:
            pre1='''
  {
    struct %(packet_name)s *tmp = fc_malloc(sizeof(*tmp));

    *tmp = *packet;
    pre_send_%(packet_name)s(pc, tmp);
    real_packet = tmp;
  }
'''
            pre2='''
  if (real_packet != packet) {
    free((void *) real_packet);
  }
'''
        else:
            pre1=""
            pre2=""

        if not self.no_packet:
            real_packet1="  const struct %(packet_name)s *real_packet = packet;\n"
        else:
            real_packet1=""

        if not self.no_packet:
            if self.delta:
                if self.want_force:
                    diff='force_to_send'
                else:
                    diff='0'
                body=self.get_delta_send_body()
                delta_header='''  %(name)s_fields fields;
  struct %(packet_name)s *old;
  bool differ;
  struct genhash **hash = pc->phs.sent + %(type)s;
  int different = %(diff)s;
'''
            else:
                body="\n"
                for field in self.fields:
                    body=body+field.get_put()+"\n"
                body=body+"\n"
                delta_header=""
        else:
            body=""
            delta_header=""

        if self.want_post_send:
            if self.no_packet:
                post="  post_send_%(packet_name)s(pc, NULL);\n"
            else:
                post="  post_send_%(packet_name)s(pc, real_packet);\n"
        else:
            post=""

        for i in range(2):
            for k,v in vars().items():
                if type(v)==type(""):
                    temp=temp.replace("<%s>"%k,v)
        return temp%self.get_dict(vars())

    # '''

    # Helper for get_send()
    def get_delta_send_body(self):
        intro='''
  if (NULL == *hash) {
    *hash = genhash_new_full(hash_%(name)s, cmp_%(name)s,
                             NULL, NULL, NULL, free);
  }
  BV_CLR_ALL(fields);

  if (!genhash_lookup(*hash, real_packet, (void **) &old)) {
    old = fc_malloc(sizeof(*old));
    *old = *real_packet;
    genhash_insert(*hash, old, old);
    memset(old, 0, sizeof(*old));
    different = 1;      /* Force to send. */
  }

'''
        body=""
        for i in range(len(self.other_fields)):
            field=self.other_fields[i]
            body=body+field.get_cmp_wrapper(i)
        if self.gen_log:
            fl='    %(log_macro)s("  no change -> discard");\n'
        else:
            fl=""
        if self.gen_stats:
            s='    stats_%(name)s_discarded++;\n'
        else:
            s=""

        if self.is_info != "no":
            body=body+'''
  if (different == 0) {
%(fl)s%(s)s<pre2>    return 0;
  }
'''%self.get_dict(vars())

        body=body+'''
  DIO_BV_PUT(&dout, fields);
'''

        for field in self.key_fields:
            body=body+field.get_put()+"\n"
        body=body+"\n"

        for i in range(len(self.other_fields)):
            field=self.other_fields[i]
            body=body+field.get_put_wrapper(self,i)
        body=body+'''
  *old = *real_packet;
'''

        # Cancel some is-info packets.
        for i in self.cancel:
            body=body+'''
  hash = pc->phs.sent + %s;
  if (NULL != *hash) {
    genhash_remove(*hash, real_packet);
  }
'''%i

        return intro+body

    # Returns a code fragment which is the implementation of the receive
    # function. This is one of the two real functions. So it is rather
    # complex to create.
    def get_receive(self):
        temp='''%(receive_prototype)s
{
<delta_header>  RECEIVE_PACKET_START(%(packet_name)s, real_packet);
<delta_body1><body1><log><body2><post>  RECEIVE_PACKET_END(real_packet);
}

'''
        if self.delta:
            delta_header='''  %(name)s_fields fields;
  struct %(packet_name)s *old;
  struct genhash **hash = pc->phs.received + %(type)s;
'''
            delta_body1="\n  DIO_BV_GET(&din, fields);\n"
            body1=""
            for field in self.key_fields:
                body1=body1+prefix("  ",field.get_get())+"\n"
            body1=body1+"\n"
            body2=self.get_delta_receive_body()
        else:
            delta_header=""
            delta_body1=""
            body1=""
            for field in self.fields:
                body1=body1+prefix("  ",field.get_get())+"\n"
            if not body1:
                body1="  real_packet->__dummy = 0xff;"
            body1=body1+"\n"
            body2=""

        if self.gen_log:
            log='  %(log_macro)s("%(name)s: got info about (%(keys_format)s)"%(keys_arg)s);\n'
        else:
            log=""
        
        if self.want_post_recv:
            post="  post_receive_%(packet_name)s(pc, real_packet);\n"
        else:
            post=""

        for i in range(2):
            for k,v in vars().items():
                if type(v)==type(""):
                    temp=temp.replace("<%s>"%k,v)
        return temp%self.get_dict(vars())

    # Helper for get_receive()
    def get_delta_receive_body(self):
        key1=map(lambda x:"    %s %s = real_packet->%s;"%(x.struct_type,x.name,x.name),self.key_fields)
        key2=map(lambda x:"    real_packet->%s = %s;"%(x.name,x.name),self.key_fields)
        key1="\n".join(key1)
        key2="\n".join(key2)
        if key1: key1=key1+"\n\n"
        if key2: key2="\n\n"+key2
        if self.gen_log:
            fl='    %(log_macro)s("  no old info");\n'
        else:
            fl=""
        body='''
  if (NULL == *hash) {
    *hash = genhash_new_full(hash_%(name)s, cmp_%(name)s,
                             NULL, NULL, NULL, free);
  }

  if (genhash_lookup(*hash, real_packet, (void **) &old)) {
    *real_packet = *old;
  } else {
%(key1)s%(fl)s    memset(real_packet, 0, sizeof(*real_packet));%(key2)s
  }

'''%self.get_dict(vars())
        for i in range(len(self.other_fields)):
            field=self.other_fields[i]
            body=body+field.get_get_wrapper(self,i)

        extro='''
  if (NULL == old) {
    old = fc_malloc(sizeof(*old));
    *old = *real_packet;
    genhash_insert(*hash, old, old);
  } else {
    *old = *real_packet;
  }
'''%self.get_dict(vars())

        # Cancel some is-info packets.
        for i in self.cancel:
            extro=extro+'''
  hash = pc->phs.received + %s;
  if (NULL != *hash) {
    genhash_remove(*hash, real_packet);
  }
'''%i

        return body+extro


# Class which represents a packet. A packet contains a list of fields.
class Packet:
    def __init__(self,str, types):
        self.types=types
        self.log_macro=use_log_macro
        self.gen_stats=generate_stats
        self.gen_log=generate_logs
        str=str.strip()
        lines=str.split("\n")
        
        mo=re.search("^\s*(\S+)\s*=\s*(\d+)\s*;\s*(.*?)\s*$",lines[0])
        assert mo,repr(lines[0])

        self.type=mo.group(1)
        self.name=self.type.lower()
        self.type_number=int(mo.group(2))
        assert 0<=self.type_number<=255
        dummy=mo.group(3)

        del lines[0]

        arr=list(item.strip() for item in dummy.split(",") if item)

        self.dirs=[]

        if "sc" in arr:
            self.dirs.append("sc")
            arr.remove("sc")
        if "cs" in arr:
            self.dirs.append("cs")
            arr.remove("cs")
        assert len(self.dirs)>0,repr(self.name)+repr(self.dirs)

        # "no" means normal packet
        # "yes" means is-info packet
        # "game" means is-game-info packet
        self.is_info="no"
        if "is-info" in arr:
            self.is_info="yes"
            arr.remove("is-info")
        if "is-game-info" in arr:
            self.is_info="game"
            arr.remove("is-game-info")

        self.want_pre_send="pre-send" in arr
        if self.want_pre_send: arr.remove("pre-send")
        
        self.want_post_recv="post-recv" in arr
        if self.want_post_recv: arr.remove("post-recv")

        self.want_post_send="post-send" in arr
        if self.want_post_send: arr.remove("post-send")

        self.delta="no-delta" not in arr
        if not self.delta: arr.remove("no-delta")

        self.no_packet="no-packet" in arr
        if self.no_packet: arr.remove("no-packet")

        self.handle_via_packet="handle-via-packet" in arr
        if self.handle_via_packet: arr.remove("handle-via-packet")

        self.handle_per_conn="handle-per-conn" in arr
        if self.handle_per_conn: arr.remove("handle-per-conn")

        self.no_handle="no-handle" in arr
        if self.no_handle: arr.remove("no-handle")

        self.dsend_given="dsend" in arr
        if self.dsend_given: arr.remove("dsend")

        self.want_lsend="lsend" in arr
        if self.want_lsend: arr.remove("lsend")

        self.want_force="force" in arr
        if self.want_force: arr.remove("force")

        self.cancel=[]
        removes=[]
        remaining=[]
        for i in arr:
            mo=re.search("^cancel\((.*)\)$",i)
            if mo:
                self.cancel.append(mo.group(1))
                continue
            remaining.append(i)
        arr=remaining

        assert len(arr)==0,repr(arr)

        if disable_delta:
            self.delta=0

        self.fields=[]
        for i in lines:
            self.fields=self.fields+parse_fields(i,types)
        self.key_fields=list(filter(lambda x:x.is_key,self.fields))
        self.other_fields=list(filter(lambda x:not x.is_key,self.fields))
        self.bits=len(self.other_fields)
        self.keys_format=", ".join(["%d"]*len(self.key_fields))
        self.keys_arg=", ".join(map(lambda x:"real_packet->"+x.name,
                                      self.key_fields))
        if self.keys_arg:
            self.keys_arg=",\n    "+self.keys_arg

        
        self.want_dsend=self.dsend_given

        if len(self.fields)==0:
            self.delta=0
            self.no_packet=1
            assert not self.want_dsend,"dsend for a packet without fields isn't useful"

        if len(self.fields)>5 or self.name.split("_")[1]=="ruleset":
            self.handle_via_packet=1

        self.extra_send_args=""
        self.extra_send_args2=""
        self.extra_send_args3=", ".join(
            map(lambda x:"%s%s"%(x.get_handle_type(), x.name),
                self.fields))
        if self.extra_send_args3:
            self.extra_send_args3=", "+self.extra_send_args3

        if not self.no_packet:
            self.extra_send_args=', const struct %(name)s *packet'%self.__dict__+self.extra_send_args
            self.extra_send_args2=', packet'+self.extra_send_args2

        if self.want_force:
            self.extra_send_args=self.extra_send_args+', bool force_to_send'
            self.extra_send_args2=self.extra_send_args2+', force_to_send'
            self.extra_send_args3=self.extra_send_args3+', bool force_to_send'

        self.receive_prototype='struct %(name)s *receive_%(name)s(struct connection *pc)'%self.__dict__
        self.send_prototype='int send_%(name)s(struct connection *pc%(extra_send_args)s)'%self.__dict__
        if self.want_lsend:
            self.lsend_prototype='void lsend_%(name)s(struct conn_list *dest%(extra_send_args)s)'%self.__dict__
        if self.want_dsend:
            self.dsend_prototype='int dsend_%(name)s(struct connection *pc%(extra_send_args3)s)'%self.__dict__
            if self.want_lsend:
                self.dlsend_prototype='void dlsend_%(name)s(struct conn_list *dest%(extra_send_args3)s)'%self.__dict__

        # create cap variants
        all_caps={}
        for f in self.fields:
            if f.add_cap:  all_caps[f.add_cap]=1
            if f.remove_cap:  all_caps[f.remove_cap]=1
                        
        all_caps=all_caps.keys()
        choices=get_choices(all_caps)
        self.variants=[]
        for i in range(len(choices)):
            poscaps=choices[i]
            negcaps=without(all_caps,poscaps)
            fields=[]
            for field in self.fields:
                if not field.add_cap and not field.remove_cap:
                    fields.append(field)
                elif field.add_cap and field.add_cap in poscaps:
                    fields.append(field)
                elif field.remove_cap and field.remove_cap in negcaps:
                    fields.append(field)
            no=i+100

            self.variants.append(Variant(poscaps,negcaps,"%s_%d"%(self.name,no),fields,self,no))


    # Returns a code fragment which contains the struct for this packet.
    def get_struct(self):
        intro="struct %(name)s {\n"%self.__dict__
        extro="};\n\n"

        body=""
        for field in self.key_fields+self.other_fields:
            body=body+"  %s;\n"%field.get_declar()
        if not body:
            body="  char __dummy;			/* to avoid malloc(0); */\n"
        return intro+body+extro
    # '''

    # Returns a code fragment which represents the prototypes of the
    # send and receive functions for the header file.
    def get_prototypes(self):
        result=(self.receive_prototype+";\n"+
                self.send_prototype+";\n")
        if self.want_lsend:
            result=result+self.lsend_prototype+";\n"
        if self.want_dsend:
            result=result+self.dsend_prototype+";\n"
            if self.want_lsend:
                result=result+self.dlsend_prototype+";\n"
        return result+"\n"

    # See Field.get_dict
    def get_dict(self,vars):
        result=self.__dict__.copy()
        result.update(vars)
        return result
    
    # Returns a code fragment which is the implementation of the
    # ensure_valid_variant function
    def get_ensure_valid_variant(self):
        result='''static void ensure_valid_variant_%(name)s(struct connection *pc)
{
  int variant = -1;

  if(pc->phs.variant[%(type)s] != -1) {
    return;
  }

  if(FALSE) {
'''%self.get_dict(vars())
        for v in self.variants:
            cond=v.condition
            name2=v.name
            no=v.no
            result=result+'  } else if(%(cond)s) {\n    variant = %(no)s;\n'%self.get_dict(vars())
        if generate_variant_logs and len(self.variants)>1:
            log='  %(log_macro)s("%(name)s: using variant=%%d cap=%%s", variant, pc->capability);\n'%self.get_dict(vars())
        else:
            log=""
        result=result+'''  } else {
    log_error("Unknown %(type)s variant for connection %%s", conn_description(pc));
    variant = -2;       /* Keep something invalid. */
  }
%(log)s  pc->phs.variant[%(type)s] = variant;
}

'''%self.get_dict(vars())
        return result


    # Returns a code fragment which is the implementation of the
    # public visible receive function
    def get_receive(self):
        only_client=len(self.dirs)==1 and self.dirs[0]=="sc"
        only_server=len(self.dirs)==1 and self.dirs[0]=="cs"
        if only_client:
            restrict='''  if (is_server()) {
    log_packet("Receiving %(name)s at the server.");
    return NULL;
  }
'''%self.get_dict(vars())
        elif only_server:
            restrict='''  if (!is_server()) {
    log_packet("Receiving %(name)s at the client.");
    return NULL;
  }
'''%self.get_dict(vars())
        else:
            restrict=""

        result='''%(receive_prototype)s
{
  if(!pc->used) {
    log_error("WARNING: trying to read data from the closed connection %%s",
              conn_description(pc));
    return NULL;
  }
  fc_assert_ret_val(NULL != pc->phs.variant, NULL);
%(restrict)s  ensure_valid_variant_%(name)s(pc);

  switch(pc->phs.variant[%(type)s]) {'''%self.get_dict(vars())
        for v in self.variants:
            name2=v.name
            no=v.no
            result=result+'''
  case %(no)s:
    return receive_%(name2)s(pc);'''%self.get_dict(vars())
        result=result+'''
  default:
    log_debug("Unknown %(type)s variant for connection %%s", conn_description(pc));
    return NULL;
  }
}
'''%self.get_dict(vars())
        return result

    def get_send(self):
        only_client=len(self.dirs)==1 and self.dirs[0]=="cs"
        only_server=len(self.dirs)==1 and self.dirs[0]=="sc"
        if only_client:
            restrict='''  if (is_server()) {
    log_error("Sending %(name)s from the server.");
  }
'''%self.get_dict(vars())
        elif only_server:
            restrict='''  if (!is_server()) {
    log_error("Sending %(name)s from the client.");
  }
'''%self.get_dict(vars())
        else:
            restrict=""

        result='''%(send_prototype)s
{
  if(!pc->used) {
    log_error("WARNING: trying to send data to the closed connection %%s",
              conn_description(pc));
    return -1;
  }
  fc_assert_ret_val(NULL != pc->phs.variant, -1);
%(restrict)s  ensure_valid_variant_%(name)s(pc);

  switch(pc->phs.variant[%(type)s]) {
'''%self.get_dict(vars())
        args="pc"
        if not self.no_packet:
            args=args+", packet"
        if self.want_force:
            args=args+", force_to_send"
        for v in self.variants:
            name2=v.name
            no=v.no



            result=result+'''
  case %(no)s:
    return send_%(name2)s(%(args)s);'''%self.get_dict(vars())
        result=result+'''
  default:
    log_debug("Unknown %(type)s variant for connection %%s", conn_description(pc));
    return -1;
  }
}
'''%self.get_dict(vars())
        return result

    def get_variants(self):
        result=""
        for v in self.variants:
            if v.delta:
                result=result+v.get_hash()
                result=result+v.get_cmp()
                result=result+v.get_bitvector()
            result=result+v.get_receive()
            result=result+v.get_send()
        result=result+self.get_ensure_valid_variant()
        return result

    # Returns a code fragment which is the implementation of the
    # lsend function.
    def get_lsend(self):
        if not self.want_lsend: return ""
        return '''%(lsend_prototype)s
{
  conn_list_iterate(dest, pconn) {
    send_%(name)s(pconn%(extra_send_args2)s);
  } conn_list_iterate_end;
}

'''%self.__dict__

    # Returns a code fragment which is the implementation of the
    # dsend function.
    def get_dsend(self):
        if not self.want_dsend: return ""
        fill="\n".join(map(lambda x:x.get_fill(),self.fields))
        return '''%(dsend_prototype)s
{
  struct %(name)s packet, *real_packet = &packet;

%(fill)s
  
  return send_%(name)s(pc, real_packet);
}

'''%self.get_dict(vars())

    # Returns a code fragment which is the implementation of the
    # dlsend function.
    def get_dlsend(self):
        if not (self.want_lsend and self.want_dsend): return ""
        fill="\n".join(map(lambda x:x.get_fill(),self.fields))
        return '''%(dlsend_prototype)s
{
  struct %(name)s packet, *real_packet = &packet;

%(fill)s
  
  lsend_%(name)s(dest, real_packet);
}

'''%self.get_dict(vars())

# Returns a code fragment which is the implementation of the
# delta_stats_report() function.
def get_report(packets):
    if not generate_stats: return 'void delta_stats_report(void) {}\n\n'
    
    intro='''
void delta_stats_report(void) {
  int i;

'''
    extro='}\n\n'
    body=""

    for p in packets:
        body=body+p.get_report_part()
    return intro+body+extro

# Returns a code fragment which is the implementation of the
# delta_stats_reset() function.
def get_reset(packets):
    if not generate_stats: return 'void delta_stats_reset(void) {}\n\n'
    intro='''
void delta_stats_reset(void) {
'''
    extro='}\n\n'
    body=""

    for p in packets:
        body=body+p.get_reset_part()
    return intro+body+extro

# Returns a code fragment which is the implementation of the
# get_packet_from_connection_helper() function. This function is a big
# switch case construct which calls the appropriate packet specific
# receive function.
def get_get_packet_helper(packets):
    intro='''void *get_packet_from_connection_helper(struct connection *pc,\n    enum packet_type type)
{
  switch (type) {

'''
    body=""
    for p in packets:
        body=body+"  case %(type)s:\n    return receive_%(name)s(pc);\n\n"%p.__dict__
    extro='''  default:
    log_packet("unknown packet type %d received from %s",
               type, conn_description(pc));
    return NULL;
  };
}

'''
    return intro+body+extro

# Returns a code fragment which is the implementation of the
# packet_name() function.
def get_packet_name(packets):
    intro='''const char *packet_name(enum packet_type type)
{
  switch (type) {

'''
    body=""
    for p in packets:
        body=body+'  case %(type)s:\n    return "%(type)s";\n\n'%p.__dict__
    extro='''  default:
    return "unknown";
  }
}

'''
    return intro+body+extro

# Returns a code fragment which is the implementation of the
# packet_has_game_info_flag() function.
def get_packet_has_game_info_flag(packets):
    intro='''bool packet_has_game_info_flag(enum packet_type type)
{
  switch (type) {

'''
    body=""
    for p in packets:
        body=body+'  case %(type)s:\n'%p.__dict__
        if p.is_info != "game":
            body=body+'    return FALSE;\n\n'
        else:
            body=body+'    return TRUE;\n\n'
    extro='''  default:
    return FALSE;
  }
}

'''
    return intro+body+extro

# Returns a code fragment which is the declartion of
# "enum packet_type".
def get_enum_packet(packets):
    intro="enum packet_type {\n"

    mapping={}
    for p in packets:
        if p.type_number in mapping :
            print(p.name,mapping[p.type_number].name)
            assert 0
        mapping[p.type_number]=p
    sorted=list(mapping.keys())
    sorted.sort()

    last=-1
    body=""
    for i in sorted:
        p=mapping[i]
        if i!=last+1:
            line="  %s = %d,"%(p.type,i)
        else:
            line="  %s,"%(p.type)

        if (i%10)==0:
            line="%-40s /* %d */"%(line,i)
        body=body+line+"\n"

        last=i
    extro='''
  PACKET_LAST  /* leave this last */
};

'''
    return intro+body+extro

def strip_c_comment(s):
  # The obvious way:
  #    s=re.sub(r"/\*(.|\n)*?\*/","",s)
  # doesn't work with python version 2.2 and 2.3.
  # Do it by hand then.
  result=""
  for i in filter(lambda x:x,s.split("/*")):
      l=i.split("*/",1)
      assert len(l)==2,repr(i)
      result=result+l[1]
  return result  

# Main function. It reads and parses the input and generates the
# various files.
def main():
    ### parsing input
    src_dir=os.path.dirname(sys.argv[0])
    src_root=src_dir+"/.."
    input_name=src_dir+"/packets.def"
    ### We call this variable target_root instead of build_root
    ### to avoid confusion as we are not building to builddir in
    ### automake sense.
    ### We build to src dir. Building to builddir causes a lot
    ### of problems we have been unable to solve.
    target_root=src_root

    content=open(input_name).read()
    content=strip_c_comment(content)
    lines=content.split("\n")
    lines=map(lambda x: re.sub("#.*$","",x),lines)
    lines=map(lambda x: re.sub("//.*$","",x),lines)
    lines=filter(lambda x:not re.search("^\s*$",x),lines)
    lines2=[]
    types=[]
    for i in lines:
        mo=re.search("^type\s+(\S+)\s*=\s*(.+)\s*$",i)
        if mo:
            types.append(Type(mo.group(1),mo.group(2)))
        else:
            lines2.append(i)

    packets=[]
    for str in re.split("(?m)^end$","\n".join(lines2)):
        str=str.strip()
        if str:
            packets.append(Packet(str,types))

    ### parsing finished

    ### writing packets_gen.h
    output_h_name=target_root+"/common/packets_gen.h"

    if lazy_overwrite:
        output_h=my_open(output_h_name+".tmp")
    else:
        output_h=my_open(output_h_name)

    output_h.write('''
#ifdef __cplusplus
extern "C" {
#endif /* __cplusplus */

/* common */
#include "disaster.h"

''')

    # write structs
    for p in packets:
        output_h.write(p.get_struct())

    output_h.write(get_enum_packet(packets))

    # write function prototypes
    for p in packets:
        output_h.write(p.get_prototypes())
    output_h.write('''
void delta_stats_report(void);
void delta_stats_reset(void);
void *get_packet_from_connection_helper(struct connection *pc, enum packet_type type);

#ifdef __cplusplus
}
#endif /* __cplusplus */
''')
    output_h.close()

    ### writing packets_gen.c
    output_c_name=target_root+"/common/packets_gen.c"
    if lazy_overwrite:
        output_c=my_open(output_c_name+".tmp")
    else:
        output_c=my_open(output_c_name)

    output_c.write('''
#ifdef HAVE_CONFIG_H
#include <fc_config.h>
#endif

#include <string.h>

/* utility */
#include "bitvector.h"
#include "capability.h"
#include "genhash.h"
#include "log.h"
#include "mem.h"
#include "support.h"

/* common */
#include "capstr.h"
#include "connection.h"
#include "dataio.h"
#include "game.h"

#include "packets.h"

static genhash_val_t hash_const(const void *vkey)
{
  return 0;
}

static bool cmp_const(const void *vkey1, const void *vkey2)
{
  return TRUE;
}

''')

    if generate_stats:
        output_c.write('''
static int stats_total_sent;

''')

    if generate_stats:
        # write stats
        for p in packets:
            output_c.write(p.get_stats())
        # write report()
    output_c.write(get_report(packets))
    output_c.write(get_reset(packets))

    output_c.write(get_get_packet_helper(packets))
    output_c.write(get_packet_name(packets))
    output_c.write(get_packet_has_game_info_flag(packets))

    # write hash, cmp, send, receive
    for p in packets:
        output_c.write(p.get_variants())
        output_c.write(p.get_receive())
        output_c.write(p.get_send())
        output_c.write(p.get_lsend())
        output_c.write(p.get_dsend())
        output_c.write(p.get_dlsend())

    output_c.close()

    if lazy_overwrite:
        for i in [output_h_name,output_c_name]:
            if os.path.isfile(i):
                old=open(i).read()
            else:
                old=""
            new=open(i+".tmp").read()
            if old!=new:
                open(i,"w").write(new)
            os.remove(i+".tmp")

    f=my_open(target_root+"/server/hand_gen.h")
    f.write('''
#ifndef FC__HAND_GEN_H
#define FC__HAND_GEN_H

/* utility */
#include "shared.h"

/* common */
#include "fc_types.h"
#include "packets.h"

struct connection;

bool server_handle_packet(enum packet_type type, const void *packet,
                          struct player *pplayer, struct connection *pconn);

''')
    
    for p in packets:
        if "cs" in p.dirs and not p.no_handle:
            a=p.name[len("packet_"):]
            type=a.split("_")[0]
            b=p.fields
            b=map(lambda x:"%s%s"%(x.get_handle_type(), x.name),b)
            b=", ".join(b)
            if b:
                b=", "+b
            if p.handle_via_packet:
                f.write('struct %s;\n'%p.name)
                if p.handle_per_conn:
                    f.write('void handle_%s(struct connection *pc, const struct %s *packet);\n'%(a,p.name))
                else:
                    f.write('void handle_%s(struct player *pplayer, const struct %s *packet);\n'%(a,p.name))
            else:
                if p.handle_per_conn:
                    f.write('void handle_%s(struct connection *pc%s);\n'%(a,b))
                else:
                    f.write('void handle_%s(struct player *pplayer%s);\n'%(a,b))
    f.write('''
#endif /* FC__HAND_GEN_H */
''')
    f.close()

    f=my_open(target_root+"/client/packhand_gen.h")
    f.write('''
#ifndef FC__PACKHAND_GEN_H
#define FC__PACKHAND_GEN_H

#ifdef __cplusplus
extern "C" {
#endif /* __cplusplus */

/* utility */
#include "shared.h"

/* common */
#include "packets.h"

bool client_handle_packet(enum packet_type type, const void *packet);

''')
    for p in packets:
        if "sc" not in p.dirs: continue

        a=p.name[len("packet_"):]
        b=p.fields
        #print len(p.fields),p.name
        b=map(lambda x:"%s%s"%(x.get_handle_type(), x.name),b)
        b=", ".join(b)
        if not b:
            b="void"
        if p.handle_via_packet:
            f.write('struct %s;\n'%p.name)
            f.write('void handle_%s(const struct %s *packet);\n'%(a,p.name))
        else:
            f.write('void handle_%s(%s);\n'%(a,b))
    f.write('''
#ifdef __cplusplus
}
#endif /* __cplusplus */

#endif /* FC__PACKHAND_GEN_H */
''')
    f.close()

    f=my_open(target_root+"/server/hand_gen.c")
    f.write('''

#ifdef HAVE_CONFIG_H
#include <fc_config.h>
#endif

/* common */
#include "packets.h"

#include "hand_gen.h"
    
bool server_handle_packet(enum packet_type type, const void *packet,
                          struct player *pplayer, struct connection *pconn)
{
  switch(type) {
''')
    for p in packets:
        if "cs" not in p.dirs: continue
        if p.no_handle: continue
        a=p.name[len("packet_"):]
        c='((const struct %s *)packet)->'%p.name
        b=[]
        for x in p.fields:
            y="%s%s"%(c,x.name)
            if x.dataio_type=="worklist":
                y="&"+y
            b.append(y)
        b=",\n      ".join(b)
        if b:
            b=",\n      "+b

        if p.handle_via_packet:
             if p.handle_per_conn:
                 args="pconn, packet"
             else:
                 args="pplayer, packet"

        else:
            if p.handle_per_conn:
                args="pconn"+b
            else:
                args="pplayer"+b

        f.write('''  case %s:
    handle_%s(%s);
    return TRUE;

'''%(p.type,a,args))
    f.write('''  default:
    return FALSE;
  }
}
''')
    f.close()

    f=my_open(target_root+"/client/packhand_gen.c")
    f.write('''

#ifdef HAVE_CONFIG_H
#include <fc_config.h>
#endif

/* common */
#include "packets.h"

#include "packhand_gen.h"
    
bool client_handle_packet(enum packet_type type, const void *packet)
{
  switch(type) {
''')
    for p in packets:
        if "sc" not in p.dirs: continue
        if p.no_handle: continue
        a=p.name[len("packet_"):]
        c='((const struct %s *)packet)->'%p.name
        b=[]
        for x in p.fields:
            y="%s%s"%(c,x.name)
            if x.dataio_type=="worklist":
                y="&"+y
            b.append(y)
        b=",\n      ".join(b)
        if b:
            b="\n      "+b

        if p.handle_via_packet:
            args="packet"
        else:
            args=b

        f.write('''  case %s:
    handle_%s(%s);
    return TRUE;

'''%(p.type,a,args))
    f.write('''  default:
    return FALSE;
  }
}
''')
    f.close()

main()
