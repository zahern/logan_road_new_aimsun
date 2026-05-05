      subroutine vms_speed(i)
c --
c -- This subroutine simulates VMS type 1 (speed advisory VMS).
c -- There are two cases for this VMS type
c --   a. if vms(i,2) is positive, then increase the link speed by a percentage
c --      (given in vms(i,3)) when the speed goes below the threshold (vms(i,2))
c --   b. if vms(i,2) is negative, then reduce the link speed by a percentage
c --      (given in vms(i,3)) when the speed goes above the threshold (vms(i,2))
c --
c -- This subroutine is called from vms_main.
c -- This subroutine does not call any subroutines 
c --
c -- INPUT :
c --  i : vms number
c -- 
c -- OUTPUT :
c -- Updated link speed.
c --
      use muc_mod
c --
c -- ilink : the link number on which the VMS is located. 
c --
      ilink=vms(i,1)
c -- 
c -- CASE 1 : increase speed
c --
      if(vms(i,2).gt.0) then
c --
c -- devide by 60 to convert the speed to mile/min
c -- 
         if(v(ilink).lt.vms(i,2)/60.0) then
           v(ilink)=(1+(vms(i,3)/100.0))*v(ilink)
         endif
      else 
c --
c -- CASE 2 : reduce speed. Note : in this case, vms(i,2) is negative
c --
           if(v(ilink).gt.vms(i,2)/(-60.0)) then
             if(vms(i,3).ge.99) vms(i,3)=99 
		   v(ilink)=(1-(vms(i,3)/100.0))*v(ilink)
           endif
      endif
c --
      return
      end
