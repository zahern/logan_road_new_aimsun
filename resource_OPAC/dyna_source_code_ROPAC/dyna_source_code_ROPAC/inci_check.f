      subroutine inci_check(tt)
c --
c -- This subroutine is the main subroutine for incident simulation
c -- it checks the start and end of incidents 
c --
c -- This subroutine is called from loop every simulation interval.
c --
c -- This subroutine calls the following subroutines
c -- 1. inci_add
c -- 2. inci_effect
c -- 3. inci_remove
c -- 4. inci_restore
c --
c -- INPUT :
c --    tt : current clock time
c --
c -- OUPUT : 
c --  No specific output.
c --
      use muc_mod
c --
c -- If the incident is starting during the current simulation interval,
c -- call inci_add to add it to the list of active incidents.
c --
      do i = 1, inci_num
         if(tt.ge.inci(i,1).and.tt.lt.inci(i,2)) then
	     if(.not.incistartflag(i)) then
             call inci_add(i)
             call inci_effect(i)
		   incistartflag(i) = .True.
	     endif
         endif
      end do
c --
c -- For all active incidents, check if any of them is ending during the
c -- current simulation interval, if yes call inci_remove to remove it 
c -- from the list of active incidents.  Then call inci_restore to adjust 
c -- the link capacity after removing the incident.
c --
      do i=1,listtotal
        if(tt.ge.inci(i,2)) then
	    if(incistartflag(i)) then
            call inci_remove(i)
            ilink=incil(i)
            call inci_restore(ilink,inci(i,3))
	   	  incistartflag(i) = .False.
	    endif
        endif 
      end do
      return
      end  
