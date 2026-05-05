      subroutine vms_divert(ilink,id_veh,kvms)
c --
c -- This subroutine simulates VMS type 3 (congestion warrning VMS).
c -- This subroutine diverts a percentage of all vehicles (vms(i,2)) to 
c -- a specific path number (vms(i,3)) for all destinations.
c --
c -- This subroutine is called from vms_main.
c -- This subroutine calls the subroutine get_veh_path
c --
c -- INPUT :
c --  i : vms number
c --
c -- OUTPUT :
c -- Updated vehicle paths for the vehicles passing by this VMS.
c --
c  -- 
      use muc_mod
	integer ipvms
c --
c -- ilink : the link on which the VMS is located.
c -- ipath : the path number to which the vehicles are switched.
c -- ipvms: 1: assign best path
c --        0: assign random path

      ipvms=vms(kvms,3)

      call DYNA_random_number(r5,11)
      
	if(r5.le.vms(kvms,2)*0.01) then ! if the vehicle responds
         call get_veh_path(id_veh,ilink,ipvms,icurrnt(id_veh)) !0 means random select paths
      endif

      return
      end
