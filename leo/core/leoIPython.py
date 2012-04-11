# -*- coding: utf-8 -*-
#@+leo-ver=5-thin
#@+node:ekr.20120401063816.10072: * @file leoIPython.py
#@@first

'''Unified support code for ILeo: the Leo-IPython bridge.

Using this bridge, scripts running in Leo can affect IPython, and vice
versa. In particular, scripts running in IPython can alter Leo outlines!

For full details, see Leo Users Guide:
http://webpages.charter.net/edreamleo/IPythonBridge.html

This module replaces both ipython.py and leo/external/ipy_leo.

Users no longer need to activate a plugin. This code will be active
provided that some version of IPyton is found on the Python path.

This module supports all versions of the IPython api:
    - legacy api: IPython to 0.11.
    - new api:    IPython 0.12 and up.
'''

#@@language python
#@@tabwidth -4

#@+<< globals >>
#@+node:ekr.20120402202350.10028: ** << globals >> (leoIPython.py)
# Globals switches...
g_trace = True
    # True: trace imports
g_use_ipapp = True
    # Used only when g_legacy == False.
    # True:  imports frontend.terminal.ipapp.  Prints signon.
    # False: frontend.terminal.interactiveshell. No signon.

# Global vars, set only at the top level...
# None of these globals requires the "global" statement.
g_import_ok = None
    # True if any IPython found.
g_ipm = None
    # The global, singleton GlobalIPythonManager instance.
g_legacy = None
    # True if IPython 0.11 or previous found.
#@-<< globals >>
#@+<< imports >>
#@+node:ekr.20120401063816.10141: ** << imports >> (leoIPython.py)
import leo.core.leoGlobals as g

import pprint
import os
import re
import sys
import time
import textwrap

if g.isPython3:
    from collections import UserDict
    UserDictMixin = UserDict
else:
    import UserDict
    UserDictMixin = UserDict.DictMixin

# for z in sys.path: print(z)

# First, try importing the legacy version of IPython.
try:
    import IPython.ipapi as ipapi
    # import IPython.genutils as genutils
    import IPython.generics as generics
    import IPython.macro as macro
    # import IPython.Shell as Shell # Used only for Shell.hijack_tk()
    from IPython.hooks import CommandChainDispatcher
    from IPython.external.simplegeneric import generic
    from IPython.ipapi import TryNext
    from IPython.genutils import SList
    g_legacy = True
    g_import_ok = True
    if g_trace: print('imported legacy IPython.ipapi')
except ImportError:
    g_legacy = False
    g_import_ok = False
except Exception:
    g_legacy = False
    g_import_ok = False
    if g_trace: print('unexpected exception importing legacy IPython')
    
if not g_import_ok:
    try:
        # Either of these works.
        if g_use_ipapp:
            tag = 'IPython.frontend.terminal.ipapp'
            import IPython.frontend.terminal.ipapp as ipapp
        else:
            tag = 'IPython.frontend.terminal.interactiveshell'
            import IPython.frontend.terminal.interactiveshell as ishell
        import IPython.utils.generics as generics
        import IPython.core.macro as macro
        from IPython.external.simplegeneric import generic
        from IPython.utils.text import SList
        from IPython.core.error import TryNext
        g_import_ok = True
        if g_trace: print('imported %s' % tag)
    except ImportError:
        pass
    except Exception:
        pass
        
if g_trace and not g_import_ok:
    print('leoIPython.py: can not import IPython')
#@-<< imports >>
#@+<< class LeoWorkBook >>
#@+node:ekr.20120401063816.10181: ** << class LeoWorkbook >>
class LeoWorkbook:
    """ class for 'advanced' node access 

    Has attributes for all "discoverable" nodes.
    Node is discoverable if it either

    - has a valid python name (Foo, bar_12)
    - is a parent of an anchor node.
    If it has a child '@a foo', it is visible as foo.

    """
    #@+others
    #@+node:ekr.20120401063816.10182: *3* __getattr__
    def __getattr__(self, key):

        if key.startswith('_') or key == 'trait_names' or not valid_attribute(key):
            raise AttributeError
        cells = all_cells()
        p = cells.get(key,None)
        if p is None:
            return add_var(key)
        else:
            return LeoNode(p)
    #@+node:ekr.20120401063816.10185: *3* __iter__
    def __iter__(self):
        """ Iterate all (even non-exposed) nodes """
        
        # cells = all_cells() # Huh???
        c = g_ipm.c
        if c:
            return (LeoNode(p) for p in c.allNodes_iter())
        else:
            return (LeoNode(p) for p in [])
    #@+node:ekr.20120401063816.10184: *3* __setattr__
    def __setattr__(self,key, val):
        raise AttributeError(
            "Direct assignment to workbook denied, try wb.%s.v = %s" % (
                key,val))

    #@+node:ekr.20120401063816.10183: *3* __str__
    def __str__(self):
        return "<LeoWorkbook>"

    __repr__ = __str__
    #@+node:ekr.20120401063816.10186: *3* current
    current = property(
        lambda self: LeoNode(c.currentPosition()),
        doc = "Currently selected node")
    #@+node:ekr.20120401063816.10187: *3* match_h
    def match_h(self,regex):
        
        cmp = re.compile(regex)
        res = PosList()
        for node in self:
            if re.match(cmp, node.h, re.IGNORECASE):
                res.append(node)
        return res
    #@+node:ekr.20120401063816.10188: *3* require
    def require(self, req):

        """ Used to control node push dependencies 

        Call this as first statement in nodes.
        If node has not been pushed, it will be pushed before proceeding

        E.g. wb.require('foo') will do wb.foo.ipush()
        if it hasn't been done already.
        """

        if req not in _leo_push_history:
            es('Require: ' + req)
            getattr(self,req).ipush()
    #@-others
#@-<< class LeoWorkBook >>

# Several defs depend on imports for types.
if g_import_ok:
    #@+others
    #@+node:ekr.20120401082519.10036: ** class GlobalIPythonManager & g_ipm
    class GlobalIPythonManager:
        
        '''A class to manage global IPython data'''
        
        #@+others
        #@+node:ekr.20120401082519.10037: *3* gipm.ctor
        def __init__ (self):
            
            self.c = None
                # The current commander, set by update_commander.
            self.ip = None
                # The global IPython instance.
            self.push_history = set()
                # The IPython history.
            self.root_node = None
                # The global root node used by the allcells() and rootnode() functions.
            self.started = False
                # True: IPython has been started.
            self.wb = LeoWorkbook()
                # The Leo workbook instance.
        #@+node:ekr.20110605121601.18482: *3* gipm.embed_ipython & helpers
        def embed_ipython(self):

            '''Run the Qt main loop using IPython if possible.'''
            
            if not g_import_ok:
                sys.exit(self.qtApp.exec_())
                    # Just run the Qt main loop.
            elif g_legacy:
                self.start_legacy_api()
            else:
                self.start_new_api()
        #@+node:ekr.20120401144849.10115: *4* gipm.start_legacy_api
        def start_legacy_api(self):

            self.started = True
            
            # No c is available: we can't get @string ipython_argv setting.
            old_argv = sys.argv
            sys.argv = ['leo.py', '-p', 'sh']         
            session = ipapi.make_session()
            self.ip = session.IP.getapi()
            self.init_ipython()
            sys.argv = old_argv

            # Does not return until IPython closes.
            # IPython runs the leo mainloop
            session.mainloop()
        #@+node:ekr.20120401144849.10116: *4* gipm.start_new_api
        def start_new_api(self):

            # No c is available: we can't get @string ipython_argv setting.
            sys.argv =  ['ipython']
            
            self.started = True

            if g_use_ipapp:
                # Prints signon.
                ipapp.launch_new_instance()
            else:
                # Doesn't print signon.
                shell = ishell.TerminalInteractiveShell()
                shell.mainloop()
        #@+node:ekr.20120401144849.10084: *3* gipm.get_history
        def get_history(self,hstart = 0):
            res = []
            
            ip = self.ip
            
            if g_legacy:
                ohist = ip.IP.output_hist
            else:
                ohist = [] ####

            for idx in range(hstart, len(ip.IP.input_hist)):
                val = ohist.get(idx,None)
                has_output = True
                inp = ip.IP.input_hist_raw[idx]
                if inp.strip():
                    res.append('In [%d]: %s' % (idx, inp))
                if val:
                    res.append(pprint.pformat(val))
                    res.append('\n')    
            return ''.join(res)
        #@+node:ekr.20120401063816.10144: *3* gipm.init_ipython
        def init_ipython(self):
            
            """ This will be run by _ip.load('ipy_leo') 

            Leo still needs to run update_commander() after this.

            """
            
            ip = self.ip
            # g.trace(ip)
            
            self.show_welcome()

            #### Shell.hijack_tk()
            ip.set_hook('complete_command',mb_completer,str_key = '%mb')

            ip.expose_magic('mb',mb_f)
            ip.expose_magic('lee',lee_f)
            ip.expose_magic('leoref',leoref_f)
            ip.expose_magic('lleo',lleo_f)    
            ip.expose_magic('lshadow',lshadow_f)
            ip.expose_magic('lno',lno_f)
            
            if 0: # Not ready yet.
                # Note that no other push command should EVER have lower than 0
                g_ipm.expose_ileo_push(push_mark_req,-1)
                g_ipm.expose_ileo_push(push_cl_node,100)
                # this should be the LAST one that will be executed,
                # and it will never raise TryNext.
                g_ipm.expose_ileo_push(push_ipython_script,1000)
                g_ipm.expose_ileo_push(push_plain_python,100)
                g_ipm.expose_ileo_push(push_ev_node,100)
            
            ip.set_hook('pre_prompt_hook',ileo_pre_prompt_hook) 
                
            # global wb
            # wb = LeoWorkbook()
            ip.user_ns['wb'] = self.wb
        #@+node:ekr.20120401144849.10094: *3* gipm.push...
        #@+node:ekr.20120401144849.10095: *4* gipm.expose_ileo_push
        def expose_ileo_push(self,f,priority=0):
            
            if g_legacy:

                self.push_from_leo.add(f,priority)
        #@+node:ekr.20120401144849.10102: *4* gipm.push_position_from_leo
        def push_position_from_leo(self,p):
            
            try:
                # self.push_from_leo(LeoNode(p))
                if g_legacy:
                    d = CommandChainDispatcher(LeoNode(p))
                    d()
                else:
                    g.trace('not ready yet')

            except AttributeError as e:
                if e.args == ("Commands instance has no attribute 'frame'",):
                    es("Error: ILeo not associated with .leo document")
                    es("Press alt+shift+I to fix!")
                else:
                    raise
        #@+node:ekr.20120401144849.10142: *4* gipm.push_to_ipython
        def push_to_ipython(self):
            
            c,ip = self.c,self.ip
            if not c:
                return g.trace('can not happen: no c.')
                
            if not self.ip:
                return g.trace('can not happen: no ip.')
                
            c.inCommand = False # Disable the command lockout logic
                
            n = LeoNode(c.p)
            
            if g_legacy:
                def f(self=self,n=n):
                    self.push_ipython_script(n)
                    return True
                d = CommandChainDispatcher()
                d.add(f)
                d()
            
            # if g_legacy:
                # self.legacy_push_to_ipython()
            # else:
                # self.new_push_to_ipython()
        #@+node:ekr.20120401144849.10143: *5* gipm.legacy_push_to_ipython
        def legacy_push_to_ipython(self):
            
            # if script:
                # gIP.runlines(script)
                # return
                
            c,ip = self.c,self.ip
            if not c:
                return g.trace('can not happen: no c.')
                
            if not self.ip:
                return g.trace('can not happen: no ip.')
                
            self.update_commander(c)
            
            push = ip.user_ns['_leo'].push
            
            g.trace(push)
            
            c.inCommand = False # Disable the command lockout logic
            push(c.p)
          
        #@+node:ekr.20120401144849.10144: *5* gipm.new_push_to_ipython
        def new_push_to_ipython (self):
            
            ip = ishell.InteractiveShell.instance()
            if not ip:
                return g.trace('can not happen: IPython not running')

            c = self.c
            if not c:
                return g.trace('can not happen: no c.')
            
            p = c.p
            if not ip.user_ns.get('_leo'):
                leox = LeoInterface(c,g)
                # ipy_leo.init_ipython(ip)
                ipy_leo.update_commander(leox,new_ip=ip)
                # g.trace('_leo',ip.user_ns.get('_leo'))
                assert ip.user_ns.get('_leo')
            c.inCommand = False
                # Disable the command lockout logic
            push = ip.user_ns['_leo'].push
                # This is really push_position_from_leo.
            push(p)
        #@+node:ekr.20120401144849.10096: *4* gipm.push_cl_node
        def push_cl_node(self,node):

            """ If node starts with @cl, eval it

            The result is put as last child of @ipy-results node, if it exists
            """

            if not node.b.startswith('@cl'):
                raise TryNext

            p2 = g.findNodeAnywhere(c,'@ipy-results')
            val = node.v
            if p2:
                es("=> @ipy-results")
                LeoNode(p2).v = val
            es(val)

        #@+node:ekr.20120401144849.10097: *4* gipm.push_ev_node
        def push_ev_node(self,node):
            
            """ If headline starts with @ev, eval it and put result in body """

            if not node.h.startswith('@ev '):
                raise TryNext

            expr = node.h.lstrip('@ev ')
            es('ipy eval ' + expr)
            res = ip.ev(expr)
            node.v = res

        #@+node:ekr.20120401144849.10098: *4* gipm.push_from_leo (not used)
        # if g_legacy:

            # push_from_leo = CommandChainDispatcher()
            
        # else:
            
            # pass

            # # def push_from_leo(self,args):
                
                # # g.trace(args)
                
                # # CommandChainDispatcher(args)
        #@+node:ekr.20120401144849.10099: *4* gipm.push_ipython_script
        def push_ipython_script(self,node):
            """ Execute the node body in IPython,
            as if it was entered in interactive prompt """
            
            c = self.c
            ip = self.ip
            # g.trace(c,node)
            try:
                ohist = ip.IP.output_hist 
                hstart = len(ip.IP.input_hist)
                script = node.script()

                # The current node _p needs to handle
                # wb.require() and recursive ipushes.
                old_p = ip.user_ns.get('_p',None)
                ip.user_ns['_p'] = node
                ip.runlines(script)
                ip.user_ns['_p'] = old_p
                if old_p is None:
                    del ip.user_ns['_p']

                has_output = False
                for idx in range(hstart,len(ip.IP.input_hist)):
                    val = ohist.get(idx,None)
                    if val is None:
                        continue
                    has_output = True
                    inp = ip.IP.input_hist[idx]
                    if inp.strip():
                        es('In: %s' % (inp[:40], ))
                    es('<%d> %s' % (idx,pprint.pformat(ohist[idx],width=40)))

                if not has_output:
                    es('ipy run: %s (%d LL)' %(node.h,len(script)))
            finally:
                c.redraw()
        #@+node:ekr.20120401144849.10100: *4* gipm.push_mark_req
        def push_mark_req(self,node):
            """ This should be the first one that gets called.

            It will mark the node as 'pushed', for wb.require.
            """

            _leo_push_history.add(node.h)
            raise TryNext
        #@+node:ekr.20120401144849.10101: *4* gipm.push_plain_python
        def push_plain_python(self,node):
            
            if not node.h.endswith('P'):
                raise TryNext

            script = node.script()
            lines = script.count('\n')
            try:
                # exec script in ip.user_ns
                # 2010/02/04: per 2to3
                exec(script,ip.user_ns)
            except:
                print(" -- Exception in script:\n"+script + "\n --")
                raise
            es('ipy plain: %s (%d LL)' % (node.h,lines))
        #@+node:ekr.20120401144849.10104: *3* gipm.run_leo_startup_node
        def run_leo_startup_node(self):
            
            c = self.c
            p = g.findNodeAnywhere(c,'@ipy-startup')
            if p:
                print("Running @ipy-startup nodes")
                for n in LeoNode(p):
                    self.push_from_leo(n)

        #@+node:ekr.20120401144849.10119: *3* gipm.show_welcome
        def show_welcome(self):

            print("------------------")
            print("Welcome to Leo-enabled IPython session!")
            print("Try %leoref for quick reference.")
            
            if g_legacy:
                import IPython.platutils as u
                u.set_term_title('ILeo')
                u.freeze_term_title()
            else:
                pass ### Not ready yet.
        #@+node:ekr.20120401063816.10145: *3* gipm.update_commander
        def update_commander(self,c):
            """ Set the Leo commander to use

            This will be run every time Leo does ipython-launch; basically,
            when the user switches the document he is focusing on, he should do
            ipython-launch to tell ILeo what document the commands apply to.

            """

            ip = self.ip
            assert ip
            
            if not c:
                return
            if ip.user_ns.get('c') == c:
                return
                
            self.c = c
            print("Set Leo Commander: %s" % c.frame.getTitle())

            leox = LeoInterface(c,g)
            leox.push = self.push_position_from_leo

            # will probably be overwritten by user,
            # but handy for experimentation early on.
            ip.user_ns['c'] = c
            ip.user_ns['g'] = g
            ip.user_ns['_leo'] = leox
                # inject leox into the namespace.

            self.run_leo_startup_node()
            ip.user_ns['_prompt_title'] = 'ileo'
        #@-others

    g_ipm = GlobalIPythonManager()
    #@+node:ekr.20120401063816.10247: ** class LeoInterface
    class LeoInterface:

        '''A class to allow full access to Leo from Ipython.

        An instance of this class called leox is typically injected
        into IPython's user_ns namespace by the init-ipython-command.'''

        def __init__(self,c,g,tag='@ipython-results'):
            self.c = c
            self.g = g
    #@+node:ekr.20120401063816.10189: ** class LeoNode
    class LeoNode(UserDictMixin): #### (object,UserDict.DictMixin):
        """ Node in Leo outline

        Most important attributes (getters/setters available:
         .v     - evaluate node, can also be aligned 
         .b, .h - body string, headline string
         .l     - value as string list

        Also supports iteration, 

        setitem / getitem (indexing):  
         wb.foo['key'] = 12
         assert wb.foo['key'].v == 12

        Note the asymmetry on setitem and getitem! Also other
        dict methods are available. 

        .ipush() - run push-to-ipython

        Minibuffer command access (tab completion works):

         mb save-to-file

        """
        #@+others
        #@+node:ekr.20120401063816.10190: *3* __init__ (LeoNode)
        def __init__(self,p):
            
            self.c = p.v.context # New in Leo 4.10.1.
            self.p = p.copy()

        #@+node:ekr.20120401063816.10191: *3* __str__
        def __str__(self):
            return "<LeoNode %s>" % str(self.p.h)

        __repr__ = __str__
        #@+node:ekr.20120401063816.10192: *3* __get_h and _set_h
        def __get_h(self):

            return self.p.headString()

        def __set_h(self,val):

            c = self.c
            c.setHeadString(self.p,val)
            LeoNode.last_edited = self
            c.redraw()

        h = property( __get_h, __set_h, doc = "Node headline string")  
        #@+node:ekr.20120401063816.10193: *3* _get_b and __set_b
        def __get_b(self):
            return self.p.bodyString()

        def __set_b(self,val):
            
            c = self.c
            c.setBodyString(self.p, val)
            LeoNode.last_edited = self
            c.redraw()

        b = property(__get_b, __set_b, doc = "Nody body string")
        #@+node:ekr.20120401063816.10194: *3* __set_val
        def __set_val(self, val):        
            self.b = format_for_leo(val)

        v = property(lambda self: eval_node(self), __set_val,
            doc = "Node evaluated value")
        #@+node:ekr.20120401063816.10195: *3* __set_l
        def __set_l(self,val):
            self.b = '\n'.join(val )

        l = property(lambda self : SList(self.b.splitlines()), 
                __set_l, doc = "Node value as string list")
        #@+node:ekr.20120401063816.10196: *3* __iter__
        def __iter__(self):
            """ Iterate through nodes direct children """

            return (LeoNode(p) for p in self.p.children_iter())

        #@+node:ekr.20120401063816.10197: *3* __children
        def __children(self):
            d = {}
            for child in self:
                head = child.h
                tup = head.split(None,1)
                if len(tup) > 1 and tup[0] == '@k':
                    d[tup[1]] = child
                    continue

                if not valid_attribute(head):
                    d[head] = child
                    continue
            return d
        #@+node:ekr.20120401063816.10198: *3* keys
        def keys(self):
            d = self.__children()
            return sorted(list(d.keys()))
        #@+node:ekr.20120401063816.10199: *3* __getitem__
        def __getitem__(self, key):
            """ wb.foo['Some stuff']
            Return a child node with headline 'Some stuff'

            If key is a valid python name (e.g. 'foo'),
            look for headline '@k foo' as well
            """  
            key = str(key)
            d = self.__children()
            return d[key]
        #@+node:ekr.20120401063816.10200: *3* __setitem__
        def __setitem__(self, key, val):
            """ You can do wb.foo['My Stuff'] = 12 to create children 

            Create 'My Stuff' as a child of foo (if it does not exist), and 
            do .v = 12 assignment.

            Exception:

            wb.foo['bar'] = 12

            will create a child with headline '@k bar',
            because bar is a valid python name and we don't want to crowd
            the WorkBook namespace with (possibly numerous) entries.
            """
            
            c = self.c
            key = str(key)
            d = self.__children()
            if key in d:
                d[key].v = val
                return

            if not valid_attribute(key):
                head = key
            else:
                head = '@k ' + key
            p = c.createLastChildNode(self.p, head, '')
            LeoNode(p).v = val

        #@+node:ekr.20120401063816.10201: *3* __delitem__
        def __delitem__(self, key):
            """ Remove child

            Allows stuff like wb.foo.clear() to remove all children
            """
            
            c = self.c
            self[key].p.doDelete()
            c.redraw()

        #@+node:ekr.20120401063816.10202: *3* ipush (LeoNode)
        def ipush(self):
            """ Does push-to-ipython on the node """
            push_from_leo(self)
        #@+node:ekr.20120401063816.10203: *3* go
        def go(self):
            """ Set node as current node (to quickly see it in Outline) """
            #c.setCurrentPosition(self.p)

            # argh, there should be another way
            #c.redraw()
            #s = self.p.bodyString()
            #c.setBodyString(self.p,s)

            c = self.c
            c.selectPosition(self.p)
        #@+node:ekr.20120401063816.10204: *3* append
        def append(self):
            """ Add new node as the last child, return the new node """
            p = self.p.insertAsLastChild()
            return LeoNode(p)
        #@+node:ekr.20120401063816.10205: *3* script
        def script(self):
            """ Method to get the 'tangled' contents of the node

            (parse @others, %s references etc.)
            """ % g.angleBrackets(' section ')

            c = self.c
            return g.getScript(c,self.p,useSelectedText=False,useSentinels=False)

        #@+node:ekr.20120401063816.10206: *3* __get_uA
        def __get_uA(self):
            
            # Create the uA if necessary.
            p = self.p
            if not hasattr(p.v,'unknownAttributes'):
                p.v.unknownAttributes = {}        

            d = p.v.unknownAttributes.setdefault('ipython', {})
            return d        

        #@-others
        uA = property(__get_uA,
            doc = "Access persistent unknownAttributes of node")
    #@+node:ekr.20120401063816.10180: ** class PosList
    class PosList(list):

        def select(self, pat):
            res = PosList()
            for n in self:
                #print "po",p
                for chi_p in n.p.children_iter():
                    #print "chi",chi_p
                    if re.match(pat, chi_p.headString()):
                        res.append(LeoNode(chi_p))
            return res
    #@+node:ekr.20120401144849.10150: ** Decorators
    #@+node:ekr.20120401144849.10079: *3* edit_object_in_leo
    @generic
    def edit_object_in_leo(obj,varname):
        
        """ Make it @cl node so it can be pushed back directly by alt+I """

        node = add_var(varname)
        formatted = format_for_leo(obj)
        if not formatted.startswith('@cl'):
            formatted = '@cl\n' + formatted
        node.b = formatted 
        node.go()
    #@+node:ekr.20120401144849.10138: ** IPython commands
    #@+node:ekr.20120401144849.10139: *3* start-ipython
    @g.command('start-ipython')
    def startIPython(event=None):

        '''The start-ipython command'''

        c = event and event.get('c') or g_ipm

        if not g_import_ok:
            g.es_print('IPython not loaded')
        elif g_ipm.started:
            g_ipm.update_commander(c)
        elif g_legacy:
            g_ipm.start_legacy_api()
        else:
            g_ipm.start_new_api()

        # if c:
            # # Just inject a new commander for current document.
            # # if we are already running.
            # leox = leoInterface(c,g) # inject leox into the namespace.
            # g_ipm.update_commander(leox)
            # return

        # try:
            # api = IPython.ipapi
            # leox = leoInterface(c,g)
                # # Inject leox into the IPython namespace.

            # existing_ip = api.get()
            # if existing_ip is None:
                # args = c.config.getString('ipython_argv')
                # if args is None:
                    # argv = ['leo.py']
                # else:
                    # # force str instead of unicode
                    # argv = [str(s) for s in args.split()] 
                # if g.app.gui.guiName() == 'qt':
                    # # qt ui takes care of the coloring (using scintilla)
                    # if '-colors' not in argv:
                        # argv.extend(['-colors','NoColor'])
                # sys.argv = argv

                # self.message('Creating IPython shell.')
                # ses = api.make_session()
                # gIP = ses.IP.getapi()

                # #if g.app.gui.guiName() == 'qt' and not g.app.useIpython:
                # if 0:
                    # # disable this code for now - --ipython is the one recommended way of using qt + ipython
                    # g.es('IPython launch failed. Start Leo with argument "--ipython" on command line!')
                    # return
                    # #try:
                    # #    import ipy_qt.qtipywidget
                    # #except:
                    # #    g.es('IPython launch failed. Start Leo with argument "--ipython" on command line!')
                    # #    raise


                    # import textwrap
                    # self.qtwidget = ipy_qt.qtipywidget.IPythonWidget()
                    # self.qtwidget.set_ipython_session(gIP)
                    # self.qtwidget.show()
                    # self.qtwidget.viewport.append(textwrap.dedent("""\
                    # Qt IPython widget (for Leo). Commands entered on box below.
                    # If you want the classic IPython text console, start leo with 'launchLeo.py --gui=qt --ipython'
                    # """))

            # else:
                # # To reuse an old IPython session, you need to launch Leo from IPython by doing:
                # #
                # # import IPython.Shell
                # # IPython.Shell.hijack_tk()
                # # %run leo.py  (in leo/leo/src)              
                # #
                # # Obviously you still need to run launch-ipython (Alt-Shift-I) to make 
                # # the document visible for ILeo

                # self.message('Reusing existing IPython shell')
                # gIP = existing_ip                

            # ipy_leo_m = gIP.load('leo.external.ipy_leo')
            # ipy_leo_m.update_commander(leox)
            # c.inCommand = False # Disable the command lockout logic, just as for scripts.
            # # start mainloop only if it's not running already
            # if existing_ip is None and g.app.gui.guiName() != 'qt':
                # # Does not return until IPython closes!
                # ses.mainloop()

        # except Exception:
            # self.error('exception creating IPython shell')
            # g.es_exception()
    #@+node:ekr.20120401144849.10140: *3* push-to-ipython
    @g.command('push-to-ipython')
    def pushToIPythonCommand(event=None):

        '''The push-to-ipython command.

        IPython must be started, but the commander need not be inited.'''
        
        trace = False and not g.unitTesting
        
        if not g_ipm.c:
            c = event.get('c')
            if c:
                g_ipm.c = c
                if trace: g.trace('setting g_ipm.c',c)
            else:
                return g.trace('can not happen: no commander')
        
        if not g_ipm.started:
            startIPython()
            
        g_ipm.push_to_ipython()
    #@+node:ekr.20120401144849.10134: ** Top-level functions
    #@+node:ekr.20120401144849.10075: *3* add_file
    def add_file(fname):
        
        c = g_ipm.c
        if c:
            p2 = c.currentPosition().insertAfter()
    #@+node:ekr.20120401144849.10076: *3* add_var
    def add_var(varname):
        
        c = g_ipm.c
        g.trace(varname)
        if not c:
            return

        r = rootnode()
        try:
            if r is None:
                p2 = g.findNodeAnywhere(c,varname)
            else:
                p2 = g.findNodeInChildren(c,r.p,varname)
            if p2:
                return LeoNode(p2)

            if r is not None:
                p2 = r.p.insertAsLastChild()

            else:
                p2 = c.currentPosition().insertAfter()

            c.setHeadString(p2,varname)
            return LeoNode(p2)
        finally:
            c.redraw()
    #@+node:ekr.20120401144849.10077: *3* all_cells
    def all_cells():

        c = g_ipm.c
        d = {}
        if not c:
            return d

        r = rootnode() 
        if r is not None:
            nodes = r.p.children_iter()
        else:
            nodes = c.allNodes_iter()

        for p in nodes:
            h = p.headString()
            if h.strip() == '@ipy-root':
                # update root node (found it for the first time)
                g_ipm.root_node = LeoNode         
                # the next recursive call will use the children of new root
                return all_cells()

            if h.startswith('@a '):
                d[h.lstrip('@a ').strip()] = p.parent().copy()
            elif not valid_attribute(h):
                continue 
            d[h] = p.copy()
        return d    
    #@+node:ekr.20120401144849.10078: *3* edit_macro
    @edit_object_in_leo.when_type(macro.Macro)
    def edit_macro(obj,varname):

        bod = '_ip.defmacro("""\\\n' + obj.value + '""")'
        node = add_var('Macro_' + varname)
        node.b = bod
        node.go()
    #@+node:ekr.20120401144849.10080: *3* es
    def es(s):
            
        g.es(s,tabName='IPython')
    #@+node:ekr.20120401144849.10081: *3* eval_body
    def eval_body(body):
        
        ip = g_ipm.ip
        
        try:
            val = ip.ev(body)
        except Exception:
            # just use stringlist if it's not completely legal python expression
            val = SList(body.splitlines())
        return val 

    #@+node:ekr.20120401144849.10082: *3* eval_node
    def eval_node(n):
        
        ip = g_ipm.ip
        if not ip: return
        
        body = n.b    
        if not body.startswith('@cl'):
            # plain python repr node, just eval it
            return ip.ev(n.b)
        # @cl nodes deserve special treatment:
        # first eval the first line (minus cl),
        # then use it to call the rest of body.
        first, rest = body.split('\n',1)
        tup = first.split(None, 1)
        # @cl alone SPECIAL USE-> dump var to user_ns
        if len(tup) == 1:
            val = ip.ev(rest)
            ip.user_ns[n.h] = val
            es("%s = %s" % (n.h, repr(val)[:20]  )) 
            return val

        cl, hd = tup 
        xformer = ip.ev(hd.strip())
        es('Transform w/ %s' % repr(xformer))
        return xformer(rest, n)
    #@+node:ekr.20120401144849.10083: *3* format_for_leo
    @generic
    def format_for_leo(obj):
        """ Convert obj to string representiation (for editing in Leo)"""
        return pprint.pformat(obj)
        
    # Just an example - note that this is a bad to actually do!
    #@verbatim
    #@format_for_leo.when_type(list)
    #def format_list(obj):
    #    return "\n".join(str(s) for s in obj)
    #@+node:ekr.20120401144849.10091: *3* mb_completer
    def mb_completer(event):
        
        """ Custom completer for minibuffer """
        
        c = g_ipm.c
        ip = g_ipm.ip

        cmd_param = event.line.split()
        if event.line.endswith(' '):
            cmd_param.append('')
            
        if len(cmd_param) > 2:
            if g_legacy:
                return ip.IP.Completer.file_matches(event.symbol)
            else:
                pass ### Not ready yet.

        return sorted(list(c.commandsDict.keys()))
    #@+node:ekr.20120401144849.10092: *3* mb_f
    def mb_f(arg):

        """ Execute leo minibuffer commands 

        Example:
         mb save-to-file
        """
        
        c = g_ipm.c
        if c:
            c.executeMinibufferCommand(arg)
    #@+node:ekr.20120401144849.10093: *3* mkbutton
    def mkbutton(text, node_to_push):
        
        c = g_ipm.c
        if c:
            ib = c.frame.getIconBarObject()
            ib.add(text=text,command=node_to_push.ipush)
    #@+node:ekr.20120401144849.10103: *3* rootnode
    def rootnode():
        """ Get ileo root node (@ipy-root) 

        if node has become invalid or has not been set, return None

        Note that the root is the *first* @ipy-root item found    
        """
        
        c = g_ipm.c
        n = g_ipm.root_node

        if n is None:
            return None
        elif c.positionExists(n.p):
            return n
        else:
            g_ipm.root_node = None
            return None  
    #@+node:ekr.20120401144849.10105: *3* shadow_walk
    def shadow_walk(directory, parent=None, isroot=True):
        """ source: http://leo.zwiki.org/CreateShadows

        """
        
        c = g_ipm.c
        if not c:
            return

        from os import listdir
        from os.path import join, abspath, basename, normpath, isfile
        from fnmatch import fnmatch

        RELATIVE_PATHS = False

        patterns_to_ignore = [
            '*.pyc', '*.leo', '*.gif', '*.png', '*.jpg', '*.json']

        match = lambda s: any(fnmatch(s, p) for p in patterns_to_ignore)

        is_ignorable = lambda s: any([ s.startswith('.'), match(s) ])

        p = c.currentPosition()

        if not RELATIVE_PATHS: directory = abspath(directory)
        if isroot:
            body = "@path %s" % normpath(directory)
            c.setHeadString(p, body)
        for name in listdir(directory):
            if is_ignorable(name):
                continue
            path = join(directory, name)
            if isfile(path):
                g.es('file:', path)
                headline = '@shadow %s' % basename(path)
                if parent:
                    node = parent
                else:
                    node = p
                child = node.insertAsLastChild()
                child.initHeadString(headline)
            else:
                g.es('dir:', path)
                headline = basename(path)
                body = "@path %s" % normpath(path)
                if parent:
                    node = parent
                else:
                    node = p
                child = node.insertAsLastChild()
                child.initHeadString(headline)
                child.initBodyString(body)
                shadow_walk(path, parent=child, isroot=False)
    #@+node:ekr.20120401144849.10107: *3* valid_attribute
    attribute_re = re.compile('^[a-zA-Z_][a-zA-Z0-9_]*$')

    def valid_attribute(s):
        return attribute_re.match(s)    
    #@+node:ekr.20120401144849.10108: *3* workbook_complete
    @generics.complete_object.when_type(LeoWorkbook)
    def workbook_complete(self,obj,prev):

        return list(all_cells().keys()) + [
            s for s in prev if not s.startswith('_')]
    #@+node:ekr.20120401144849.10109: ** Top-level IPython magic functions
    # By IPython convention, these must have "self" as the first argument.
    #@+node:ekr.20120401144849.10085: *3* ileo_pre_prompt_hook
    def ileo_pre_prompt_hook(self):
        
        c = g_ipm.c
        if c:
            c.outerUpdate()

        raise TryNext

        # old code

            # # this will fail if leo is not running yet
            # try:
                # c.outerUpdate()
            # except (NameError, AttributeError):
                # pass
            # raise TryNext
    #@+node:ekr.20120401144849.10086: *3* lee_f
    def lee_f(self,s):
        
        """ Open file(s)/objects in Leo

        - %lee hist -> open full session history in leo
        - Takes an object. l = [1,2,"hello"]; %lee l.
          Alt+I in leo pushes the object back
        - Takes an mglob pattern, e.g. '%lee *.cpp' or %lee 'rec:*.cpp'
        - Takes input history indices:  %lee 4 6-8 10 12-47
        """

        # import os

        c = g_ipm.c
        ip = g_ipm.ip
        wb = g_ipm.wb

        try:
            if s == 'hist':
                if c:
                    wb.ipython_history.b = g_ipm.get_history()
                    wb.ipython_history.go()
                else:
                    g.trace('no c')
                return

            if s and s[0].isdigit():
                # numbers; push input slices to leo
                lines = self.extract_input_slices(s.strip().split(), True)
                v = add_var('stored_ipython_input')
                v.b = '\n'.join(lines)
                return

            # try editing the object directly
            obj = ip.user_ns.get(s, None)
            if obj is not None:
                edit_object_in_leo(obj,s)
                return
                
            if not c:
                # print('file not found: %s' % s)
                return

            # if it's not object, it's a file name / mglob pattern
            from IPython.external import mglob

            files = (os.path.abspath(f) for f in mglob.expand(s))
            for fname in files:
                p = g.findNodeAnywhere(c,'@auto ' + fname)
                if not p:
                    p = c.currentPosition().insertAfter()

                p.setHeadString('@auto ' + fname)
                if os.path.isfile(fname):
                    c.setBodyString(p,open(fname).read())
                c.selectPosition(p)
            print("Editing file(s), \
                press ctrl+shift+w in Leo to write @auto nodes")
        finally:
            if c:
                c.redraw()
    #@+node:ekr.20120401144849.10087: *3* leoref_f
    def leoref_f(self,s):
        """ Quick reference for ILeo """

        print(textwrap.dedent("""\
        %lee file/object - open file / object in leo
        %lleo Launch leo (use if you started ipython first!)
        wb.foo.v  - eval node foo (i.e. headstring is 'foo' or '@ipy foo')
        wb.foo.v = 12 - assign to body of node foo
        wb.foo.b - read or write the body of node foo
        wb.foo.l - body of node foo as string list

        for el in wb.foo:
          print el.v

        """
        ))
    #@+node:ekr.20120401144849.10088: *3* lleo_f
    def lleo_f(selg,args):
        """ Launch leo from within IPython

        This command will return immediately when Leo has been
        launched, leaving a Leo session that is connected 
        with current IPython session (once you press alt+I in leo)

        Usage::
          lleo foo.leo
          lleo 
        """

        import os
        import sys
        import shlex
        argv = shlex.split(args)
        ip = g_ipm.ip
        if not ip: return

        # when run without args, leo will open ipython_notebook for 
        # quick note taking / experimentation

        if not argv:
            argv = [os.path.join(ip.options.ipythondir,'ipython_notebook.leo')]

        sys.argv = ['leo'] + argv

        # Set the --ipython option. 
            # global _request_immediate_connect
            # _request_immediate_connect = True.
            
        if '--ipython' not in sys.argv:
            sys.argv.append ('--ipython')
        
        import leo.core.runLeo
        leo.core.runLeo.run()
    #@+node:ekr.20120401144849.10089: *3* lno_f
    def lno_f(self, arg):
        """ %lno [note text]

        Gather quick notes to leo notebook

        """

        wb = g_ipm.wb

        try:
            scr = wb.Scratch
        except AttributeError:
            print("No leo yet, attempt launch of notebook...")
            lleo_f(self,'')
            scr = wb.Scratch

        child = scr.get(arg, None)
        if child is None:
            scr[arg] = time.asctime()
            child = scr[arg]

        child.go()
    #@+node:ekr.20120401144849.10090: *3* lshadow_f
    def lshadow_f(self, arg):
        """ lshadow [path] 

        Create shadow nodes for path (default .)

        """
        
        c = g_ipm.c
        if c:
            if not arg.split():
                arg = '.'
            p = c.p.insertAfter()
            c.setCurrentPosition(p)
            shadow_walk(arg)
            c.redraw()
    #@-others
#@-leo