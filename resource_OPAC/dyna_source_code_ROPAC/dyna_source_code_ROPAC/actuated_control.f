      subroutine actuated_control(nodenumber,ll)
c --
c -- This subroutine calculates the green time for each approach, if the intersection has actuated signal control.
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
      integer gtemp,casa,ll
      real t_now	
c --
c -- nip : the controlled intersection
c -- n1 : the starting phase for the current intersection
c -- n2 : the ending phase for the current intersection
c --
      nip=nodenumber
      n1=kgpoint(nip)
      n2=kgpoint(nip+1)-1
c --
c -- initialize the critical link for all phases
c --
      do i=1,nu_ph1
         cmalink(i)=1
      enddo
c --
c -- calculate the lost time for the current intersection
c --
       lost_time=0
       do i=n1,n2
         lost_time=lost_time+nsign(i,4)
       enddo
c --
c -- initialize the pseudo_cycle
c --
      pseudo_cycle=0 
c --
c --  t_now is the start of the current simulation interval
c --  since tii in in minutes, it should be multiplied by 60 to convert it into seconds.
c --
      t_now=time_now-tii*60
c --
c -- t_act is the end of the current simulation interval.
c --
      t_act=time_now
c -- 
c -- define the critical link and its vehicle_queue.
c -- the critical link is the link with the maximum queue during each phase.
c --
c -- phase is a varibale to keep track of the current phase number.
c --
c -- Note : the difference between n1, n2 and phase is the following
c -- n1 and n2 are calculated by sorting all the phases in the network.
c -- n1 and n2 define the starting and ending phases for the current node.
c -- The "phase" is just the phase number, provided in the control input file, at the current node.
c-- linktmp => critical link
c --
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
      do 900 i=n1,n2
      phase=nsign(i,1)
      cma_time(phase)=cma(phase)/MaxFlowRate(cmalink(phase))
900   continue
c  --
c  -- iphase is an index to keep track of the active phase number. 
c  --
      iphase=0
      do ik=n1,n2
         if(t_now.le.nsign(ik,13)) then 
               iphase=ik
             goto 2000
         endif
      enddo
2000  continue
c --
c -- gtmp is a temprary variable to keep the assigned green time for the current phase.
c --
c -- NOTE : nsign(iphase,13) defines the end of green for phase iphase.
c -- In this case, the value for nsign(iphase,13) is dynamically allocted (i.e. it is not a predefined value).
c --
      gtmp=cma_time(nsign(iphase,1))
      if(t_now+gtmp.ge.nsign(iphase,13))then
c -- 
c -- check if gmax is exceeded.  
c --
         if((nsign(iphase,13)+gtmp-nsign(iphase,12))
     +   .gt.nsign(iphase,2))then 
            gtmp=nsign(iphase,2)+nsign(iphase,12)-nsign(iphase,13)
         endif
c --
c -- check for minimum green
c --
         if((nsign(iphase,13)+gtmp-nsign(iphase,12))
     +                           .lt.nsign(iphase,3))then
            gtmp=nsign(iphase,3)+nsign(iphase,12)-nsign(iphase,13)
         endif
c --
c -- redefine the start and end of green time for all consequent phases
c -- according to the allocated green time to the current phase (iphase).
c --
         nsign(iphase,13)=nsign(iphase,13)+gtmp
         nsign(iphase,14)=nsign(iphase,14)+gtmp
         do ik=iphase+1,n2
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


1300   do 100 nu=n1,n2
       iphase=nsign(nu,1)
c -- 
c -- g is a variable to keep the green time value for the current phase
c --
       gtemp=0

c --  Old_definition (with an error):
c       if(t_now.ge.nsign(nu,12).and.t_act.lt.nsign(nu,13)) then
c                 gtemp=t_act-t_now
c       elseif(t_act.gt.nsign(nu,13).and.t_now.le.nsign(nu,13)) then
c                 gtemp=nsign(nu,13)-t_now
c       elseif(t_act.ge.nsign(nu,12).and.t_now.lt.nsign(nu,12)) then
c                 gtemp=t_act-nsign(nu,12)
c      endif

c --  Alex_new_definition:

       if(t_now.ge.nsign(nu,12).and.t_act.le.nsign(nu,13))then
                 gtemp=t_act-t_now
       elseif(t_act.gt.nsign(nu,13).and.t_now.le.nsign(nu,13))then
                 gtemp=nsign(nu,13)-t_now
       elseif(t_act.ge.nsign(nu,12).and.t_now.lt.nsign(nu,12))then
                 gtemp=t_act-nsign(nu,12)
       elseif(t_act.gt.nsign(nu,13).and.t_now.lt.nsign(nu,12))then
                 gtemp=nsign(nu,13)-nsign(nu,12)
       endif
c --
c -- allocate the green for each movement in the current phase (iphase)
c --
               do 200 m=6,5+nsign(nu,5)
		          lnum=nsign(nu,m)
		          do 200 mg=1,llink(lnum,nu_mv+1)
c        if(nodenumber.eq.5)then						  
c      print *, 'sctuated',mg,llink(lnum,nu_mv+1),lnum,nu_mv,nu,n1,
c     +	  green(lnum,mg)	
c        endif	 
                     if(nu.gt.n1)then
                       if(green(lnum,mg).gt.0) goto 200
                     endif 
                  green(lnum,mg)=gtemp*movement(lnum,iphase,mg)
				  
c        if(nodenumber.eq.120)then				  
c       print *, green(lnum,mg),vehicle_queue(lnum),lnum,mg,ll
c        endif
		
200    continue
100    continue
c  --
      if(iflg.eq.1)then
c --
c -- if this is the end of a cycle, then set the starting and ending times iassumming minimum greeen for all phases as initial value.
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
		
      pause
	  
      endif

c	if(nodenumber.eq.32)then
c	casa=GetFLinkFromNode(idnum(33),idnum(32))
c	print *,iunod(casa),idnod(casa),casa
c      do j=1,llink(casa,nu_mv+1)
c           print *, green(casa,j)
c      enddo
c	pause
c 	endif
c        if(nodenumber.eq.120) pause
	  
      return
      end



