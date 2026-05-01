      subroutine vms_main(t_start)
c --
c -- This is the main subroutine for VMS operations.
c --
c -- This subroutine is called from loop every simulation interval
c -- This subroutine calls the following subroutines :
c -- 	a. vms_speed
c --	b. vms_path  
c --  c. vms_divert
c -- 
c -- INPUT : 
c -- the current clock time (through common blocks)
c --
c -- OUTPUT : 
c -- No specific output (it just manages the VMS files)
c --
      use muc_mod
c --
c --
c -- There are three different types of VMS :
c -- 1. speed reduction
c -- 2. assign a specific path
c -- 3. divert vehciles to other paths
c -- assumption :
c -- 1. the position of vms is known
c -- 2. the time of operation is known
c --
      if(vms_num.gt.0) then  
        do i=1,vms_num
          if(t_start.ge.vms_start(i).and.
     +                  t_start.lt.vms_end(i)) then
            if(vmstype(i).eq.1) then
		     call vms_speed(i)

	      endif
          endif
        end do
      endif
c --
      return
      end
