        subroutine link_pricing

c --
c -- This subroutine prepares the HOV link cost (toll) values according to the 
c -- pricing scheme.
c -- The cost for each HOV link differ based on the occupancy of the vehicle.
c -- Higher Occupancy Vehicles are expected to have a lower cost than Lower Occupancy
c -- vehicles when they pass the same link.
c --
  

      use muc_mod

       do ia=1,noofarcs
         do ic=1,no_occupancy_level
           do lp=1,no_link_type 
		 ! no_link_type = 1: no HOV links, no_link_type = 2: with HOV links, 
           ia1=ForToBackLink(ia)

             cost(ia1,lp,ic)= price_regular

!******************************************

! Link type 10: HOV/Freeway
!            if(link_iden(ia).eq.8) then ! HOV link
       if(link_iden(ia).eq.8.or.link_iden(ia).eq.10) then ! HOV link
!******************************************


!              LOV on HOV link: put high penalty 10000 
              if (ic.eq.1)  cost(ia1,lp,ic)=PenForHOV ! defined in muc_mod_td  

!              HOV on HOV link: 0
              if (ic.eq.2)  cost(ia1,lp,ic)=0.0
		   endif


!******************************************

! Link type 9: HOT/Freeway
!           if(link_iden(ia).eq.6) then ! HOT link
       if(link_iden(ia).eq.6.or.link_iden(ia).eq.9) then ! HOT link
!******************************************

		  if (ic.eq.1) cost(ia1,lp,ic)=price_hot_lov
           if (ic.eq.2) cost(ia1,lp,ic)=price_hot_hov
            endif

         enddo
         enddo
       enddo

      return
      end


