      subroutine pretimed_control(nodenumber)
c --
c -- This subroutine calculates the green time for each approach if the
c -- intersection has pretimed control.
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
      integer gtemp
      real t_now	  
c --
c --
c --  t_now is the start of the current simulation interval
c --  since tii in in minutes, it should be multiplied by 60 to
c --   convert it into seconds.
c --
      t_now=time_now-tii*60
c --
c -- t_next is the end of the current simulation interval.
c --
      t_next=time_now
c --
c -- nm : the controlled intersection
c -- n1 : the starting phase for the current intersection
c -- n2 : the ending phase for the current intersection
c --
      nm = nodenumber   !G

      gcycle=node(nodenumber,4)
      n1=kgpoint(nm)
      n2=kgpoint(nm+1)-1
c --
c -- if there is coordination, then consider the offsets at the begining 
c -- of each signal setting plan.
c --
c -- Update the starting time for each phase to consider the offset.
c -- 
      if(t_now.eq.strtsig(isigcount)) then
        offset=nsign(n1,2)
        n_cycle=(offset/gcycle)+1
        idiff=offset-n_cycle*gcycle
        i_tm=idiff
        do n=n1,n2
          nsign(n,12)=i_tm+nsign(n,12)
          nsign(n,13)=nsign(n,12)+nsign(n,3)
          nsign(n,14)=nsign(n,13)+nsign(n,4)
          i_tm=nsign(n,14)
        enddo 
      endif
c --
c --
c -- iflg is a flag to check if this is the end of a cycle
c -- iflg=1, if this is the end of a cycle and 0 otherwise.
c --
         iflg=0
         if(t_next.gt.nsign(n2,14)) then
           t_next=nsign(n2,14)
           iflg=1
           t_old=t_next
         endif
c --
12    do 100 i=n1,n2
      iphase=NSIGN(i,1)
c --
c -- g is a variable to keep the green time value for the current phase
c --
      gtemp=0
      if(t_now.ge.nsign(i,12).and.t_next.lt.nsign(i,13)) then
         gtemp=t_next-t_now
      elseif(t_now.le.nsign(i,13).and.t_next.gt.nsign(i,13)) then
         gtemp=nsign(i,13)-t_now
      elseif(t_next.ge.nsign(i,12).and.t_now.lt.nsign(i,12)) then
         gtemp=t_next-nsign(i,12)
      endif
c --
c -- Limit the green time during each simulation interval to a maximum of
c -- the simulation interval length (in seconds)
c --
      if(gtemp.gt.tii*60) gtemp=tii*60
      if(gtemp.lt.0.05) g=0.0

c --
c -- allocate the green for each movement in the current phase (iphase)
c --
        do 200 m=6,nsign(i,5)+5
	     le=llink(nsign(i,m),nu_mv+1)
	     lnum=nsign(i,m)
	     do 200 li=1,le
             if(i.gt.n1) then
               if(green(lnum,li).gt.0) go to 200
             endif
	       green(lnum,li)=gtemp*movement(lnum,iphase,li)
200          continue
100   continue
c --
      if(iflg.eq.1) then
c --
c -- if this is the end of a cycle, then set the starting and ending
c -- times assumming minimum greeen for all phases as initial value.
c --
        tmp=t_next
        do nuw=n1,n2
          nsign(nuw,12)=tmp
          nsign(nuw,13)=tmp+nsign(nuw,3)
          tmp=nsign(nuw,13)+nsign(nuw,4) 
          nsign(nuw,14)=tmp
        enddo   
        t_next=t_now+tii*60
        t_now=t_old
        iflg=0
c --
c -- if iflg=1, this means that the green time has been allocated for
c -- the last phase for the current intersection and there may exist some
c -- green time to be allocated to the first phase in the next cycle.
c -- So, return back and calculate the possible green for all phases.
c --
        go to 12
      endif
      return
      end
