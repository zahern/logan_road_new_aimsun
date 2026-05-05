      subroutine inci_remove(i)
c --
c -- This subroutine removes an incident from the list of active incidents.
c --
c -- This subroutine is called from inci_check
c -- This subbroutine does not call any subroutines
c --
c -- INPUT :
c --   i : the incident number which cleared up during the current simulation
c --       interval
c --
c -- OUTPUT :
c --   mofdified list of active incidents
c --
      use muc_mod
c -- 
      incilist(i)=0
      do ii=1,inci_num
      itp(ii)=incilist(ii)
      end do
      kk=0
         do k=1,listtotal
            if(incilist(k).ne.0) then
               kk=kk+1
               incilist(kk)=itp(k)
            endif
         end do
      return
      end
