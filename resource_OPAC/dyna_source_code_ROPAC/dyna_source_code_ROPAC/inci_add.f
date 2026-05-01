      subroutine inci_add(i)
c --
c --  This subroutine adds an incident to the list of active incidents.
c --
c --  This subroutine is called from inci_check.
c --  This subroutine does not call any subroutines.
c --
c -- INPUT :
c --   i : incident number
c --
c -- OUTPUT :
c --   updated list of active incidents
c --
      use muc_mod
c  --
c -- listtotal : is the number of active incidents
c -- seve : is the severity of the current incident.
c --
      listtotal=listtotal+1
      incilist(listtotal)=i
      ilink=incil(i)
      seve=inci(i,3)
      return
      end
 