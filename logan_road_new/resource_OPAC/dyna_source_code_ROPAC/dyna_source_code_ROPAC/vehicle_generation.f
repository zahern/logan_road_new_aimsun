      subroutine vehicle_generation(t,i,j)
c --
c -- This subroutne assigns attributes to the newly generated vehicles.
c --
c -- This subroutine is called from vehicle_loading
c -- This subroutine does not call any other subroutines
c --
c -- INPUT :
c --  t : current clock time 
c --  i : current link
c --  j : the ID for the generated vehicle
c --
c -- OUTPUT :
c --  attributes for vehicle j.
c --d
      use muc_mod
	real CumDemtmp(10) ! CumDemTmp() is the temporary array the store the accum prob for a gen link from which it receives demand
      integer misscount
	real r0,r1,r2,r3,r4
c  -- For reading vehicle files
c --
c  -- B1. skip this part if reading from vehicle file
c  -- or iteration >= 1
      if(realdm.eq.1.and.iteration.lt.1)then
c --
c -- istrm : seed number for the random number generation function.
c --
      call DYNA_random_number(r0,8) 
!              xpar(j)=s(i)/2.0
!              xpar(j)=s(i)*r0
!      need to compare UE and 1shot consistently
c --
	        xpar(j)=s(i)
c --
              if(t.ge.starttm.and.t.lt.endtm)then
			   itag(j)=1
                 numcars=numcars+1
	        else
	           itag(j)=0
              endif
c --
c --  assign the vehicle class.
c -- 
c --  assign muc_veh
      muc_veh(vehclass(j))=muc_veh(vehclass(j))+1
c --
c -- calculate the relative indifference band and complince for each vehicle.
c --
c -- Set the starting time for the current vehicle to the current clock time.
c -- set the generation (starting) link to the current link.
c --
              stime(j)=t
!              isec(j)=i
c --
c -- Assign the vehicle destination. 
c --
! --  in case that link i is receiving demand from more than one zone, 
! --  we need to first determine which super zone this link is receiving demand by drawing
! --  randome and check the zfdem
!	mDemID = 0 ! indext to indicate which original zone that link i is receiving demand from
	           ! such information is specified in original.dat
!	DemSum = 0.0
c --
c  -- under regular muc, assign one destination
        DestVisit(j) = 1 
        NoOfIntDst(j) = 1
        IntDestZone(j,NoOfIntDst(j))=jdest(j) ! jdest carries original zone number        
c --
c -- assign the vehicle type, considering the fact that vehicle calss 4
c -- (boundedly rational) should have a vehicle type 4,5 or 6 only.
c --
c -- assign mtnum for each vehicle (the equavlency factor for the vehicle
c -- if it is a truck then mtnum=2.5
c --
c              r3=ran3(istrm)
!              call DYNA_random_number(r3,8)
              if(vehclass2(j).eq.2) mtnum(j)=1.5 ! according to HCM 1998, it should be 1.5 as default
              if(vehclass2(j).eq.5) mtnum(j)=1.5
c --
c  -- B1
      endif
c --
c -- assign level of occupation for the vehicle.
c -- ioc(j)= 1, lower occupancy vehicle
c -- ioc(j)= 2, higher occupancy vehicle   
c --
      return
      end 
