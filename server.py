import socket, threading, json, time, random, string
HOST='0.0.0.0'; PORT=5056
rooms={}; lock=threading.RLock()
def send(c,obj):
 try:c.sendall((json.dumps(obj,ensure_ascii=False)+'\n').encode())
 except OSError:pass
def broadcast(room,obj):
 for p in list(room['players'].values()):send(p['conn'],obj)
def finish_grab(code,pid,target):
 with lock:
  room=rooms.get(code)
  if not room:return
  p=room['players'].get(pid);victim=room['players'].get(target)
  if not p or not victim or p.get('pending')!=target or victim.get('pending_owner')!=pid:return
  p['pending']=None
  if (p['held'] is not None or p['heldby'] is not None or
      victim['heldby'] is not None or victim['held'] is not None or
      victim.get('pending') is not None or victim.get('pending_owner')!=pid):
   if victim.get('pending_owner')==pid:victim['pending_owner']=None
   return
  victim['pending_owner']=None
  p['held']=target;victim['heldby']=pid
  broadcast(room,{'type':'grab','id':pid,'target':target})

def handle(c,addr):
 code=None; pid=None
 try:
  f=c.makefile('r',encoding='utf-8'); hello=json.loads(f.readline()); mode=hello.get('mode'); name=str(hello.get('name','Player'))[:16]; color=int(hello.get('color',0))%6
  with lock:
   if mode=='create':
    code=''.join(random.choices(string.ascii_uppercase+string.digits,k=5))
    while code in rooms:code=''.join(random.choices(string.ascii_uppercase+string.digits,k=5))
    rooms[code]={'players':{},'stage':0,'start':False,'host':None,'last_stage_advance':0.}
   else:
    code=str(hello.get('room','')).upper().strip()
    if code not in rooms:send(c,{'type':'error','message':'Không tìm thấy phòng'});return
   room=rooms[code]
   if room['start']:
    send(c,{'type':'error','message':'Phòng đang chơi, vui lòng đợi vòng sau'});return
   if len(room['players'])>=6:send(c,{'type':'error','message':'Phòng đã đầy'});return
   pid=''.join(random.choices(string.ascii_lowercase+string.digits,k=8))
   if room.get('host') is None:room['host']=pid
   room['players'][pid]={'conn':c,'name':name,'color':color,'x':100+len(room['players'])*50,'y':480,'face':1,'held':None,'heldby':None,'pending':None,'pending_owner':None,'ready':False}
   send(c,{'type':'welcome','id':pid,'room':code,'stage':room['stage'],'started':room['start'],'host':room['host']})
   sync(room)
  for line in f:
   try:msg=json.loads(line)
   except ValueError:continue
   with lock:
    if code not in rooms or pid not in rooms[code]['players']:break
    room=rooms[code]; p=room['players'][pid]; typ=msg.get('type')
    if typ=='state':
     p['x']=max(0,min(11000,float(msg.get('x',p['x']))));p['y']=max(-500,min(900,float(msg.get('y',p['y']))));p['face']=1 if msg.get('face',1)>=0 else -1
     broadcast(room,{'type':'state','id':pid,'x':p['x'],'y':p['y'],'face':p['face']})
    elif typ=='ready':
     if not room['start']:
      p['ready']=bool(msg.get('ready',False));sync(room)
    elif typ=='start':
     if pid!=room['host'] or len(room['players'])<2 or not all(p.get('ready') for p in room['players'].values()):continue
     # Starting a session always resets the authoritative room state.
     room['stage']=0;room['start']=True;room['last_stage_advance']=time.monotonic()
     for index,player in enumerate(room['players'].values()):
      player.update(x=100+index*55,y=450,face=1,held=None,heldby=None,pending=None,pending_owner=None)
     broadcast(room,{'type':'stage','stage':0})
     sync(room)
     broadcast(room,{'type':'start'})
    elif typ=='next':
     if not room['start'] or pid!=room['host']:continue
     if room['stage']<8 and time.monotonic()-room['last_stage_advance']>2.0:
      room['last_stage_advance']=time.monotonic()
      room['stage']+=1;broadcast(room,{'type':'stage','stage':room['stage']})
    elif typ=='grab':
     target=msg.get('target'); victim=room['players'].get(target)
     if (room['start'] and victim and target!=pid and p['held'] is None and p.get('pending') is None and
         p['heldby'] is None and victim['heldby'] is None and victim['held'] is None and
         victim.get('pending') is None and victim.get('pending_owner') is None and
         abs(p['x']-victim['x'])<=128 and abs(p['y']-victim['y'])<=100):
      broadcast(room,{'type':'action','action':'suck','id':pid,'target':target})
      p['pending']=target
      # Reserving the victim immediately prevents two opposing grabs in flight.
      victim['pending_owner']=pid
      timer=threading.Timer(0.46,finish_grab,args=(code,pid,target))
      timer.daemon=True;timer.start()
    elif typ=='throw':
     if not room['start']:continue
     try:power=float(msg.get('power',.4))
     except (ValueError,TypeError):power=.4
     power=max(.22,min(1.0,power))
     target=p['held']
     if target in room['players']:
      victim=room['players'][target]
      victim['heldby']=None;p['held']=None
      victim['x']=p['x']+p['face']*50;victim['y']=p['y']-40
      broadcast(room,{'type':'action','action':'throw','id':pid,'target':target})
      broadcast(room,{'type':'throw','id':pid,'target':target,'vx':p['face']*(200+460*power),'vy':-(185+275*power)})
      broadcast(room,{'type':'state','id':target,'x':victim['x'],'y':victim['y'],'face':victim['face']})
 except (OSError,ValueError,TypeError,ConnectionError) as e:print('Disconnected:',addr,e)
 finally:
  with lock:
   if code in rooms and pid in rooms[code]['players']:
    for other in rooms[code]['players'].values():
     if other.get('held')==pid:other['held']=None
     if other.get('pending')==pid:other['pending']=None
     if other.get('heldby')==pid:other['heldby']=None
     if other.get('pending_owner')==pid:other['pending_owner']=None
    del rooms[code]['players'][pid]
    if not rooms[code]['players']:del rooms[code]
    else:
     if rooms[code]['host']==pid:rooms[code]['host']=next(iter(rooms[code]['players']))
     if not rooms[code]['start']:
      for player in rooms[code]['players'].values():player['ready']=False
     sync(rooms[code])
  try:c.close()
  except OSError:pass
def sync(room):
 broadcast(room,{'type':'roster','players':{k:{a:v for a,v in p.items() if a!='conn'} for k,p in room['players'].items()}})
 broadcast(room,{'type':'ready','ready':{k:p.get('ready',False) for k,p in room['players'].items()},'host':room['host']})
if __name__=='__main__':
 s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind((HOST,PORT));s.listen();print('Croak Squad server running on port',PORT)
 while True:
  c,a=s.accept();c.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1);threading.Thread(target=handle,args=(c,a),daemon=True).start()
