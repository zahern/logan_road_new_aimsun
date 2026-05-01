      subroutine vms_path(ilink,id_veh,kvms)


	!this subroutine is not called!
c --
c -- This subroutine simulates VMS type 2 (route advisory VMS).
c -- There are two cases for this VMS type
c --   a. if vms(i,3) equal a destination number, then switch the vehicles
c --      going to that specific destination to path number vms(i,2)
c --   b. if vms(i,3) =0, then switch all vehicles to path number vms(i,2).
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
      use muc_mod
c --
c -- ilink : the link on which the VMS is located.
c -- nodee : the downstream node of ilink.
c -- ipath : the path number to which the vehicles are switched.
c --
             ipath=vms(kvms,2)

	       call get_veh_path(id_veh,ilink,ipath,icurrnt(id_veh))

      return
      end
