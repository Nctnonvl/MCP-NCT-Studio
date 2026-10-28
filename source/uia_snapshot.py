"""One bounded UIA tree acquisition, reusable local subtree views per observation."""
import time
from functools import cached_property
from types import SimpleNamespace

class CachedNode:
 def __init__(self,node):self._node=node;self._properties={}
 def __getattr__(self,name):
  if name not in self._properties:self._properties[name]=getattr(self._node,name)
  return self._properties[name]
 @cached_property
 def children(self):return tuple(CachedNode(child) for child in self._node.GetChildren())
 def GetChildren(self):return self.children
 @cached_property
 def legacy(self):
  pattern=self._node.GetLegacyIAccessiblePattern()
  return SimpleNamespace(Value=pattern.Value) if pattern else None
 def GetLegacyIAccessiblePattern(self):return self.legacy


def capture(root,limit=10000,seconds=10):
 deadline=time.monotonic()+seconds;entries=[];complete=True
 def visit(node,path=()):
  nonlocal complete
  if len(entries)>=limit or time.monotonic()>deadline:complete=False;return
  entries.append((node,path))
  try:children=node.GetChildren()
  except Exception:
   complete=False;return
  for child in children:
   if not complete:return
   visit(child,path+(node,))
 visit(CachedNode(root))
 return entries,complete


def subtree(entries,scope):
 for node,path in entries:
  if node is scope:yield node,()
  elif scope in path:
   index=path.index(scope)
   yield node,path[index:]
