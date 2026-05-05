      subroutine ropac_3(nodenumber)
c	  ,llink,time_now,
c     + nodenum,noofnodes,kgpoint,cmalink,nu_ph1,nsign,nu_mv,tii2,
c     + vehicle_queue,narcs,cma,SatFlowRate,cma_time,green,movement)
c --
c -- This subroutine calculates the green time for each approach,
c -- if the intersection has actuated signal control.
c --
c -- This subroutine is called from intersection_control.
c -- This subroutine does not call any other subroutines.
c --
c -- INPUT :
c -- nodenumber : the intersection number.
c --
c -- OUTPUT :
c --  green times for each approach and each movement.
c --
      use muc_mod

      REAL, DIMENSION(1:100)::cma_time_3
      integer FFropac,g,n1,n2,nip,i,iphaseRT,lost_time,linktmp,j
      integer iflg,nu,m,mg,lnum,nw,t,ik
      real t_now,tii2
      integer nodenumber	  
c      real gtmp,t_act,t_old,time_now
	  
c      integer nodenum(noofnodes),kgpoint(noofnodes+1),cmalink(nu_ph1)
c      integer nsign(noofnodes*nu_mv,14),vehicle_queue(narcs)
c      integer green(narcs,nu_mv),movement(narcs,nu_ph1,nu_mv)
c      integer llink(narcs,nu_mv+1),phase		  
c      real cma(nu_ph1),SatFlowRate(narcs),cma_time(nu_ph1)	  
c --
c -- nip : the controlled intersection
c -- n1 : the starting phase for the current intersection
c -- n2 : the ending phase for the current intersection
c --
c      print *,'Alex221'
      nip=nodenum(nodenumber)
      n1=kgpoint(nip)
      n2=kgpoint(nip+1)-1
c --
c -- initialize the critical link for all phases
c --
c      print *,'Alex222'
      do i=1,nu_ph1
         cmalink(i)=1
      end do
c --
c -- calculate the lost time for the current intersection
c --
c      print *,'Alex223'
       lost_time=0
       do i=n1,n2
         lost_time=lost_time+nsign(i,4)
       enddo
c --
c -- initialize the pseudo_cycle
c --
c      pseudo_cycle=0 
c --
c --  t_now is the start of the current simulation interval
c --  since tii in in minutes, it should be multiplied by 60 to
c --  convert it into seconds.
c --
      t_now=time_now-tii*60
c --
c -- t_act is the end of the current simulation interval.
c --
      t_act=time_now
c -- 
c -- define the critical link and its vehicle_queue.
c -- the critical link is the link with the maximum queue
c -- during each phase.
c --
c -- phase is a varibale to keep track of the current phase number.
c --
c -- Note : the difference between n1, n2 and phase is the following
c -- n1 and n2 are calculated by sorting all the phases in the network.
c -- n1 and n2 define the starting and ending phases for the current node.
c -- The "phase" is just the phase number, provided in the control input
c -- file, at the current node.
c --
c      print *,'Alex224'
      do 600 i=n1,n2
        phase=nsign(i,1)
        cma(phase)=0
        do 700 j=6,nsign(i,5)+5
             linktmp=nsign(i,j)
          if(cma(phase).le.vehicle_queue(linktmp))then
              cma(phase)=vehicle_queue(linktmp)
              cmalink(phase)=linktmp
           endif
700     continue
600   continue

c --
c -- determine the extension of the green time by calculating the required
c -- time to discharge the maximum queue according to the saturation flow rate.
c --
c      print *,'Alex225'
	  
      do 900 i=n1,n2
      phase=nsign(i,1)
      cma_time(phase)=cma(phase)/SatFlowRate(cmalink(phase))
900   continue
c	write(2,*) 1
c	write(2,24) (cma_time(i), i=1, n2-n1+1)

c  --
c  -- iphase is an index to keep track of the active phase number. 
c  --
c      print *,'Alex226'
	  
       iphaseRT=0
       do ik=n1,n2
         if(t_now.le.nsign(ik,13))then 
               iphaseRT=ik
             goto 2000
         endif
       enddo
2000  continue

c --
c -- gtmp is a temprary variable to keep the assigned green time for the current phase.
c --
c -- NOTE : nsign(iphase,13) defines the end of green for phase iphase.
c --        In this case, the value for nsign(iphase,13) is dynamically
c --        allocted (i.e. it is not a predefined value).
c --

c      print *,'Alex227'
	  
      gtmp=cma_time(nsign(iphaseRT,1))

      if(t_now+gtmp.ge.nsign(iphaseRT,13))then
c -- 
c -- check if gmax is exceeded.  
c --
         if((nsign(iphaseRT,13)+gtmp-nsign(iphaseRT,12))
     +   .gt.nsign(iphaseRT,2))then 
            gtmp=nsign(iphaseRT,2)+nsign(iphaseRT,12)-nsign(iphaseRT,13)
         endif
c --
c -- check for minimum green
c --
         if((nsign(iphaseRT,13)+gtmp-nsign(iphaseRT,12))
     +                           .lt.nsign(iphaseRT,3))then
            gtmp=nsign(iphaseRT,3)+nsign(iphaseRT,12)-nsign(iphaseRT,13)
         endif
c --
c -- redefine the start and end of green time for all consequent phases
c -- according to the allocated green time to the current phase (iphase).
c --
         nsign(iphaseRT,13)=nsign(iphaseRT,13)+gtmp
         nsign(iphaseRT,14)=nsign(iphaseRT,14)+gtmp
         do ik=iphaseRT+1,n2
           nsign(ik,12)=nsign(ik,12)+gtmp
           nsign(ik,13)=nsign(ik,13)+gtmp
           nsign(ik,14)=nsign(ik,14)+gtmp
         enddo
      endif
c --
c -- iflg is a flag to check if this is the end of a cycle
c -- iflg=1, if this is the end of a cycle and 0 otherwise.
c --
      iflg=0
      if(t_act.ge.nsign(n2,13))then 
             iflg=1
          if(t_act.ge.nsign(n2,14))then
             t_act=nsign(n2,14)
             t_old=t_act
          endif
       endif
c --
c      print *,'Alex228'

1300   do 100 nu=n1,n2
       iphaseRT=nsign(nu,1)
c -- 
c -- g is a variable to keep the green time value for the current phase
c --
       g=0
       if(t_now.ge.nsign(nu,12).and.t_act.le.nsign(nu,13))then
                 g=t_act-t_now
c	 write(2,*) 'lili 1'
       elseif(t_act.gt.nsign(nu,13).and.t_now.le.nsign(nu,13))then
                 g=nsign(nu,13)-t_now
c	 write(2,*) 'lili 2'
       elseif(t_act.ge.nsign(nu,12).and.t_now.lt.nsign(nu,12))then
                 g=t_act-nsign(nu,12)
c	 write(2,*) 'lili 3'
	 elseif(t_act.gt.nsign(nu,13).and.t_now.lt.nsign(nu,12))then
			     g=nsign(nu,13)-nsign(nu,12)
c	 write(2,*) 'lili 4'
       endif

      FFropac=nu-n1+1
      cma_time_3(FFropac)=g		            !

c --
c -- allocate the green for each movement in the current phase (iphase)
c --
               do 200 m=6,5+nsign(nu,5)
		        lnum=nsign(nu,m)
		        do 200 mg=1,llink(lnum,nu_mv+1)
                 if(nu.gt.n1)then
                   if(green(lnum,mg).gt.0) go to 200
                 endif 
                 green(lnum,mg)=g*movement(lnum,iphaseRT,mg)
200    continue
100    continue
c  --
c  --
c	write(2,24) (cma_time_3(i), i=1, n2-n1+1)          
c      print *,'Alex229'
	  
      if(iflg.eq.1)then
c --
c -- if this is the end of a cycle, then set the starting and ending
c -- times iassumming minimum greeen for all phases as initial value.
c --
         t=nsign(n2,14)
         do nw=n1,n2
	       nsign(nw,12)=t
           nsign(nw,13)=t+nsign(nw,3)
	       nsign(nw,14)=nsign(nw,13)+nsign(nw,4)
           t=nsign(nw,14)
         enddo
c --
c --  Reset iflg, t_act and t_now
c --
c      print *,'Alex2210'
	  
        iflg=0
        t_act=t_now+tii*60
        t_now=t_old
c --
c -- if iflg=1, this means that the green time has been allocated for
c -- the last phase for the current intersection and there may exist some
c -- green time to be allocated to the first phase in the next cycle.
c -- So, return back and calculate the possible green for all phases.
c --
        goto 1300
      endif
c      print *,'Alex2211'
	  
24    format(10f7.1)

      return
      end
