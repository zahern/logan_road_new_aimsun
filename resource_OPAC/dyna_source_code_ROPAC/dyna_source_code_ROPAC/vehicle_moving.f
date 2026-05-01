      subroutine vehicle_moving(t,endtime)
! --
! --This subroutine moves the vehicles on the links and checks
! --if they reach the destination.
! --
! --This subroutine is called from vehicle_simulation
! --This subroutine calls : bus_imapct and getlink
! --
! --INPUT :
! --  t : the start of the current simulation interval
! --
! --OUTPUT :
! --  updated vehicle positions on all links
! --  updated link information
! --
        use muc_mod
        use vector_mod
        use LinkList_mod
        use Intooi_mod

        logical::ArriveIntDest=.False.
        integer Nlnk,CuLnk
! --
! --loop over all links and all vehicles on the link
! --
C	if(iteration.gt.0)print *, 'Alex0' 

     	intoo(:)%NVehIn = 0
     	intoo(:)%NVehOut = 0

     	do 7 i=1,noofarcs
! --
! --j : the vehicle ID
! --xposold : position of the vehicle on the link at the begining of the current time interval.
! --xpos : position of the vehicle on the link at the end of the current time interval.
! --
C	if(iteration.gt.0)print *, 'Alex01'

        p_mtxj_value=>LinkVehList(i)
        kj = 0

C	if(iteration.gt.0)print *, 'Alex02'

        if(npar(i).gt.0.and.p_mtxj_value%veh.lt.1)then
          print *, 'error in npar and mtxj'
        endif

! -- This do while loop is to go through all the vehicle in the LinkVehList(i)
! -- move the vehicles and check if the vehicle reach the destinations
        do while(p_mtxj_value%veh.gt.0)  
C	if(iteration.gt.0)print *, 'Alex000' 
          kj=kj+1
          j=p_mtxj_value%veh
C	if (j.eq.42)
C	if(iteration.gt.0)print *, 'Alex001'

         if(j.eq.15338.and.iteration.eq.2.and.t.gt.300)then
            iiidebug=1
         endif

        xposold=xpar(j)
        xpos=xpar(j)-v(i)*tii
        tocross(j)=xpar(j)/v(i)
        tleft(j)=tii-tocross(j)
		
c        if(j.eq.1)then
c    		print *,xposold,xpos,v(i)*tii,vtmp(i)*tii,tocross(j),i
c            pause			
c        endif
		 
c	if(iteration.gt.0)print *, 'Alex002' 
! -- record this vehicle if it passes the middle of the link (for accumulated volume)

          if(t.ge.starttm.and.t.lt.endtm)then
            if(xposold.gt.s(i)/2.0.and.xpos.le.s(i)/2.0)then
			   AccuVol(i)=AccuVol(i)+1
			   LinkVolume(i)=LinkVolume(i)+1
            endif
          endif
! --
! --if the vehicle is a bus, then consider its effect on the netwrok.
! --
! --imbus : a flag to know if the bus is stopping or not.  
! --       if =0, then the bus is not stopping on this link during
! --       the current simulation interval, and 1 otherwise.
! --
C	if(iteration.gt.0)print *, 'Alex003'  

          imbus=0
          if(vehclass2(j).eq.7)then
              call bus_impact(i,j,xpos,imbus)

C	if(iteration.gt.0)print *, 'Alex004' 
! --
! -- update the travel distanse for the current vehicle.
! --if imbus=1, then all the bus claculations have been performed in
! --the bus_imapct subroutine, so the code does not calculate any 
! --information for this bus.
! --
		if(xpos.gt.0.and.imbus.eq.0) distans(j)=distans(j)+v(i)*tii
		if(xpos.le.0.and.imbus.eq.0) distans(j)=distans(j)+xpar(j)
		if(imbus.eq.1) go to 8
! --go to 8 means skip the rest for this vehilce 
! --because all the calculations have been performed in the bus_impact.
! --
          endif

! -- update distans j
		distans(j)=distans(j)+max(0.0,min(xpar(j),v(i)*tii))


! --if xpos is greater than zero, then the vehicle is still on the link
! --and did not reach the downstream node of the link.  Then, update the
! --vehicle position and travel time.
! --
c	if (j.eq.42)
C	if(iteration.gt.0)print *, 'Alex005

c	if(j.eq.4092) then
c	print *,'Alex4092',i,iunod(i),idnod(i),xposold,xpos
c	pause
c	endif

		if(xpos.gt.0.0)then  ! HGF big if the following for those have not reached stop bar
		   xpar(j)=xpos
             ttilnow(j)=ttilnow(j)+tii
! --     add to GUITotalTime
             GuiTotalTime=GuiTotalTime+tii

! --
! --if the current link is a freeway link with detector, then
! --calculate the occupancy of the detector on this link.
! --
! --      if(link_iden(i).eq.2) then
		   if(link_detector(i).gt.0)then !DET
			  xposold=xposold*5280
			  xposnew=xpos*5280
! --
! --NOTE : xposold and xposnew are measured from the downstream node
! --       of the link.
! -- 
			  idec=link_detector(i)
			  if(idec.gt.0)then
				itmp1=detector(idec,4)
				itmp2=detector(idec,5)
			  endif
! --
! --Calculate occup(idec) : the occupied lane length of the detector. 
! --(the lane length of the detector = detector length * # of lanes).
! --

			if(xposold.gt.itmp1.and.xposnew.lt.itmp2)then
				occup(idec)=occup(idec)+detector_length(idec)
			elseif(xposold.lt.itmp1.and.xposnew.gt.itmp2)then
				occup(idec)=occup(idec)+vehicle_length
			elseif(xposold.gt.itmp1.and.xposnew.gt.itmp2.and.
     +			xposnew.lt.itmp1)then
				occup(idec)=occup(idec)+(itmp1-xposnew)
			elseif(xposold.lt.itmp1.and.xposold.gt.itmp2.and.
     +			xposnew.lt.itmp2)then
				occup(idec)=occup(idec)+(xposold-itmp2)
			endif
		endif !DET
C	if(iteration.gt.0)print *, 'Alex006' 
!        go to 8

!      endif

c        print *,t,endtime,tii,realdm

c        if(abs(t-(endtime-1)*tii).lt.0.001.and.realdm.ne.1)then
c	print *,'Alex001'
c           call links_travel_time(i,j,t)
c        endif	

      else														! HGF vehicles have reached the end of the link
c	if (j.eq.42)
C	if(iteration.gt.0)print *, 'Alex007'
! --
! --
! --if the above condition is not satisfied, then the vehicle has reached the end of the link.
! --
! --count how many vehicles are ready to move out
C	if(iteration.gt.0)print *, 'Alex11215'
        if(iteration.gt.0)then
			iiidebbug=1
        endif
C	if(iteration.gt.0)print *, 'Alex112151'
		Intoo(i)%NVehOut=Intoo(i)%NVehOut+1
C	if(iteration.gt.0)print *, 'Alex112152'
        ttilnow(J)=ttilnow(J)+tocross(j)
! --    add to GUITotalTime
C	if(iteration.gt.0)print *, 'Alex112153',j
        GuiTotalTime=GuiTotalTime+tocross(j)

c	if (j.eq.42)
C	if(iteration.gt.0)print *,'Alex11220',t,j,i,icurrnt(j),Nlnk
! --get the next link

c        if(abs(t-(endtime-1)*tii).lt.0.001.and.realdm.ne.1)then
c             call links_travel_time(i,j,t)
c        endif
		 
        call getlink(t,j,i,icurrnt(j),Nlnk)
	    nexlink(j)=Nlnk
C	if(iteration.gt.0)print *, 'Alex11230'  
! --
! --nl is the next link for  vehicle j
! --
	    nl=Nlnk

c	if(j.eq.4092) then
c	print *,'Alex4092',i,iunod(i),idnod(i),nl,idnod(nl)
c	pause
c	endif
	   
! -- This part is to check if the vehicle will reach the intermediate 
! -- destination (not the final one) within currnt sim interval. If so, 
! -- Hold it at the intermediate destination

      if(NoOfIntDst(j).gt.1.and.DestVisit(j).lt.NoOfIntDst(j))then

! if iteration = 0, only check if the downstream node of the nl is the centroid
! howevew, for iteration > 0 and for class 1 and 5 which need to keep paths got from iteration = 0
! we need to use IntDestPath to know when to take the vehicle out to the intermediate destination
          ArriveIntDest = .False.
          if(iteration.eq.0) then
			if(idnod(nl).eq.destination(MasterDest(IntDestZone(
     +		j,DestVisit(j))))) ArriveIntDest=.True.
          else
		if(vehclass(j).eq.2.or.vehclass(j).eq.3) then
			if(idnod(nl).eq.destination(MasterDest(IntDestZone(
     +			j,DestVisit(j))))) ArriveIntDest=.True.
			else
			if(icurrnt(j).eq.IntDestPath(j,DestVisit(j))) 
     +			ArriveIntDest = .True.
			endif
          endif
	    if(ArriveIntDest) then
			call TripChain_Insert(i,j) ! Insert the vehicle to list that carrys vehicles exit the network for activity
	        call mtxj_remove(i,j) ! remove this vehicle out of the current link
			npar(i)=npar(i)-1
		if(vehclass2(j).eq.2.or.vehclass2(j).eq.5.or.vehclass2(j).eq.7) 
     +		nTruck(i)=nTruck(i)-1
	        volume(i)=volume(i)-1
			if(volume(i).lt.0) then
				write(911,*)'Negative volume on link',i
				write(911,*)'Please contact developers'
				stop
			endif
			partotal(i)=partotal(i)-mtnum(j)
			RemainDwell(j)=IntDestDwell(j,DestVisit(j))-tleft(j) ! start counting the remaining dewell time for the current activity
			IntDestPath(j,DestVisit(j)) = icurrnt(j) ! record the number of nodes on the path 
			tocross(j)=0.0
			tleft(j)=0.0
	        goto 8
          endif
	endif
c	if(iteration.gt.0)print *, 'Alex11240'  
! --
! --Check if the downstram node for the current link is the final destination for
! --the current vehicle. If yes, call get_veh_stat and if not call getlink.
! --
! -- check idnod(nl) for centroid case.  Take vehicles out when they
! -- reach the connectors/destination, not the actual centroid

c	if(j.eq.4092) then
c	print *,'Alex4092',t,i,nl,idnod(nl),
c	+destination(MasterDest(IntDestZone(j,NoOfIntDst(j))))
c	+,iunod(i),idnod(i)
c	endif

      if((idnod(nl).eq.destination(MasterDest(IntDestZone(j,
     + NoOfIntDst(j))))).and.(DestVisit(j).ge.NoOfIntDst(j)))then
			
          call get_veh_stat(i,j,t) ! get the stats for this vehicle
          call mtxj_remove(i,j) ! take this vehicle out of the network
	      npar(i)=npar(i)-1
	  if(vehclass2(j).eq.2.or.vehclass2(j).eq.5.or.vehclass2(j).eq.7) 
     +  nTruck(i)=nTruck(i)-1
	    volume(i)=volume(i)-1
		if(volume(i).lt.0) then
			write(911,*)'Negative volume on link',i
			write(911,*)'Please contact developers'
			stop
		endif
		partotal(i)=partotal(i)-mtnum(j)
	    xpar(j)=0.0
		IntDestPath(j,DestVisit(j)) = icurrnt(j)
	    goto 8

      else 

c	if(iteration.gt.0)print *, 'Alex11250'

! --check if this link has VMS, if so, update the path for 
! --this vehicle based on the information preemption mode
! -- If InfoPM = 0: In-vehicle info preemts VMS, only class 5 respond to VMS
! --             1: VMS preempts in-vehicle, class 2-5 will respond to VMS (except class 1)


!  if(inci_num.gt.0.or.WorkZoneNum.gt.0) then
! if(ImpactType(j)%InciIM.gt.0.or.ImpactType(j)%WZIM.gt.0) then

	if(vms_num.gt.0) then ! if there is VMS, check  **** A1
   		do kvms=1,vms_num !A2
      	if(time_now/60.0.ge.vms_start(kvms).and.time_now/60.0
     +	.lt.vms_end(kvms))then !A3
			if(i.eq.vms(kvms,1))then !A4
!            if((InfoPM.eq.1.and.vehclass(j).eq.5).or.(InfoPM.eq.0.and.(vehclass(j).ne.1))) then   !A5


        if((InfoPM.eq.0.and.vehclass(j).eq.5).or.(InfoPM.eq.1.and.
     +  (vehclass(j).ne.1)))then   !A5
               if(vmstype(kvms).eq.3)then !A6
                  call vms_divert(i,j,kvms)
                  call getlink(t,j,i,icurrnt(j),Nlnk)
			      nexlink(j) = Nlnk
	              nl = Nlnk
! --           define ImpactType based on diversion

         if(inci_num.gt.0.or.WorkZoneNum.gt.0) then !*  A7
         if(ImpactType(j)%InciIM.gt.0.or.ImpactType(j)%WZIM.gt.0) then !** A8
         if(ImpactType(j)%InciIM.gt.0) then  !A9
         do JO = ImpactType(j)%InciIM, ImpactType(j)%InciIM !B1
         if(Nlnk.eq.incil(JO)) then ! next immediate link is an incident link  B2
	ImpactType(j)%InciMode = 1

			       endif !B2
                              enddo !B1
                           endif !A9 
               
			               kflag = 0
	if(ImpactType(j)%WZIM.gt.0) then  !B6
        do JO = ImpactType(j)%WZIM, ImpactType(j)%WZIM !B7
        if(Nlnk.eq.GetFLinkFromNode(WorkZone(JO)%FNode,
     +  WorkZone(JO)%TNode)) then ! next immediate link is an incident link !B8
		ImpactType(j)%WZMode = 1


			       endif !B8
                           enddo !B7
				endif   !B6
	                 endif !A8
			      endif !A7
			   endif !A6
            endif	!A5


! All vehicles need to follow type 2 VMS      
            if(vmstype(kvms).eq.2) then !C3
               Index1D = icurrnt(j)
    	       icflag = 0
               do mp = 1, vms(kvms,3) !no of nodes in the detour path  C4

!nov 12, for DYNA 930.8
				  !value = float(vmstypetwopath(kvms,mp)%node)
	value = float(idnum(vmstypetwopath(kvms,mp)%node))
    		      call VhcAtt_Insert(j,Index1D,1,value)
	    	      Index1D = Index1D + 1
               enddo  !C4 
c	if(iteration.gt.0)print *, 'Alex11260'                                 
			call get_veh_path(j,vmstypetwopath(kvms,vms(kvms,3)-1)%
     +		link,1,Index1D-1) !# of link is # of node less 1
              call getlink(t,j,i,icurrnt(j),Nlnk)
	        nexlink(j) = Nlnk
			nl=Nlnk

               if(inci_num.gt.0.or.WorkZoneNum.gt.0) then !*  C5
	if(ImpactType(j)%InciIM.gt.0.or.ImpactType(j)%WZIM.gt.0) then !** C6

! -- define ImpactType based on diversion
                     if(inci_num.gt.0) then  !C7
                        if(ImpactType(j)%InciIM.gt.0) then  !C8
	do JO = ImpactType(j)%InciIM, ImpactType(j)%InciIM !C9
                              if(Nlnk.eq.incil(JO)) then ! next immediate link is an incident link !D1
		              ImpactType(j)%InciMode = 1
			                  
			               endif !D1

				   enddo !C9
			         endif !C8
                  endif !inci_num.gt.0 !C7

                  kflag = 0
                  if(WorkZoneNum.gt.0) then  !D5
                     if(ImpactType(j)%WZIM.gt.0) then  !D6
           do JO = ImpactType(j)%WZIM, ImpactType(j)%WZIM !D7
	if(Nlnk.eq.GetFLinkFromNode(WorkZone(JO)%FNode,
     +  WorkZone(JO)%TNode)) then ! D8 next immediate link is an incident link
		ImpactType(j)%WZMode = 1
			                        
			endif !D8 Nlnk.eq.GetFLinkFromNode(WorkZone(JO)%FNode,WorkZone(JO)%FNode)
                       enddo !D7
				        endif !D6
                     endif  ! D5 WorkZoneNum.gt.0
	              endif !C6 **
			   endif !C5 *
            endif ! C3 vmstype(kvms).eq.2
         endif !A5
      	endif !A3  
   	enddo !A2

c	if(iteration.gt.0)print *, 'Alex11270'  
!endif A1

! need to get impacted statistics even if no vms exists*************************

	else

	if(inci_num.gt.0.or.WorkZoneNum.gt.0) then !*  A77
        if(ImpactType(j)%InciIM.gt.0.or.ImpactType(j)%
     +  WZIM.gt.0) then !** A88
        if(ImpactType(j)%InciIM.gt.0) then  !A99
        do JO = ImpactType(j)%InciIM, ImpactType(j)%InciIM !B11
        if(Nlnk.eq.incil(JO)) then ! B22 next immediate link is an incident link  
		ImpactType(j)%InciMode = 1
		endif
        enddo !B11
        endif !A99 
               
		kflag = 0
        if(ImpactType(j)%WZIM.gt.0) then  !B66
        do JO = ImpactType(j)%WZIM,ImpactType(j)%WZIM !B77

!if(Nlnk.eq.GetFLinkFromNode(WorkZone(JO)%FNode,WorkZone(JO)%FNode)) then !E1

	if(Nlnk.eq.GetFLinkFromNode(WorkZone(JO)%FNode,
     +  WorkZone(JO)%TNode)) then !  !B88 next immediate link is an incident link
		ImpactType(j)%WZMode = 1
    			            endif !C11
	                         enddo !B99                     
				endif   !B66
	                 endif !A88
			      endif !A77

!****************************************************************************************
!****************************************************************************************
!****************************************************************************************

	endif !A1 ****


! -- check if the next link is HOV lane or not
!	if(link_iden(nl).eq.6) HovFlag(j) = .true.


!	if(link_iden(nl).eq.8) HOVFlag(j) = .true.
	if(link_iden(nl).eq.8.or.link_iden(nl).eq.10) HOVFlag(j) = .true.
	if(link_iden(nl).eq.6.or.link_iden(nl).eq.9) HOTFlag(j) = .true.
! --
! --get the index for the nexlink.
! --
      jerror=0
! --
      do nlii=1,llink(i,nu_mv+1)
         if(llink(i,nlii).eq.nl)then 
            nlindex=nlii
            jerror=1
	      exit
         endif
      enddo
! --
! -- Check for error : if the next link is not one of the downstream
! -- links of the current link, then stop.
! --
      if(jerror.eq.0) then
       write(911,*) 'ERROR:   next link'
       write(911,*) 'J I idnod(i) NL iunod(nl)',j,i,idnod(i),nl,
     + destination(jdest(j)),isec(j), jdest(j),vehclass2(j),
     + DestVisit(j),NoOfIntDst(j)
       write(911,*) 'icu info vehclass',icurrnt(j),info(j),vehclass(j)
       stop
      endif
143   format('jpath: ',10i5)
! --

! --
! --if there is a left turn bay, the vehicle is making a left turn
! --movement and there exist capacity for the current link,
! --then the vehicle is ready to move to the next link. 
! --
! -- pre-processing left_capacity and capacity if they are below 1.0

c	goto 1020
	 
	if(left_capacity(i).lt.1.0.and.left_capacity(i).ge.0.00001)then
           call random_number(r1)
           if(r1.lt.left_capacity(i)) then
		      left_capacity(i)=1.0
		   else
		      left_capacity(i)=0.0
           endif
	endif

c	print *,'AlexCheckRiht01=',right_capacity(i),'i=',i,'r1=',r1
c	pause

      if(right_capacity(i).lt.1.0.and.right_capacity(i).ge.0.00001)then
           call random_number(r1)
           if(r1.lt.right_capacity(i))then
		      right_capacity(i)=1.0
		   else
		      right_capacity(i)=0.0
           endif
	endif

c	print *,'AlexCheckRiht02=',right_capacity(i),'i=',i,'r1=',r1
c	pause

!*****************************************************************************
c	if(iteration.gt.0)print *, 'Alex11280'  

1020  if(capacity(i,nlindex).lt.1.0.and.capacity(i,nlindex).ge.
     +  0.00001)then
           call random_number(r1)
           if(r1.lt.capacity(i,nlindex))then
		      capacity(i,nlindex)=1.0
		   else
		      capacity(i,nlindex)=0.0
           endif
	endif

!      if(move(i,nlindex).eq.1.and.left_capacity(i).gt.0.and.captot(i)/nlanes(i).gt.0) then

c	if(j.eq.4092)then
c	print *,'AlexRightCheck',move(i,nlindex),right_capacity(i),i
c	pause
c	endif

c	if(j.eq.4092)then
c	print *,'AlexLeftCheck',move(i,nlindex),left_capacity(i),i
c	pause
c	endif

	if(move(i,nlindex).eq.1.and.left_capacity(i).gt.0)then


c	if(j.eq.4092)then
c	print *,'AlexLeft'
c	pause
c	endif

		if(bay(i).gt.0)then		! with left turn bay
		left_capacity(i)=left_capacity(i)-1.0 

        intoo(nl)%NVehIn=intoo(nl)%NVehIn+1
        call TranLink_Insert(nl,intoo(nl)%NVehIn,1,j)
        call TranLink_Insert(nl,intoo(nl)%NVehIn,2,i)
        call TranLink_Insert(nl,intoo(nl)%NVehIn,3,kj)
!       intooi(nl,intoo(nl)%NVehIn,1)=j
!       intooi(nl,intoo(nl)%NVehIn,2)=i
!       intooi(nl,intoo(nl)%NVehIn,3)=kj
		endif

		if(bay(i).eq.0)then			! without left turn bay
			if(captot(i).gt.0)then 
		left_capacity(i)=left_capacity(i)-1.0 
			captot(i) = captot(i) -1 !need to reduce tot capacity as well

          intoo(nl)%NVehIn=intoo(nl)%NVehIn+1
          call TranLink_Insert(nl,intoo(nl)%NVehIn,1,j)
          call TranLink_Insert(nl,intoo(nl)%NVehIn,2,i)
          call TranLink_Insert(nl,intoo(nl)%NVehIn,3,kj)
!         intooi(nl,intoo(nl)%NVehIn,1)=j
!         intooi(nl,intoo(nl)%NVehIn,2)=i
!         intooi(nl,intoo(nl)%NVehIn,3)=kj
			endif
		endif


	elseif(move(i,nlindex).eq.3.and.right_capacity(i).gt.0)then

c	if(j.eq.4092)then
c	print *,'AlexRight'
c	pause
c	endif

		if(bayR(i).gt.0)then						! with right turn bay
			if(link_iden(i).eq.1.or.link_iden(i).eq.2)then !capacity in freeway is in pcphpl, so need to factor in PCE when determining # of vehicles to move
				if(qflag(j)) then


!the number of vehicles from capacity for DYNA 930.8
! MaxFlowRate(i) is already corrected (reduced for presence of left turn vehicles and heavy trucks
! therefore MaxFlowRate(i)/SatFlowRate(i) is less than 1.0
!				right_capacity(i)=right_capacity(i)-(MaxFlowRate(i)/SatFlowRate(i))*mtnum(j)
	right_capacity(i)=right_capacity(i)-(MaxFlowRateOrig(i)/
     +  SatFlowRate(i))*mtnum(j)
			
				else
			right_capacity(i)=right_capacity(i)-1.0*mtnum(j) 
				endif
			else ! capacity in arterials is in vphpl and is computed using MaxFlowRate
				if(qflag(j)) then


!the number of vehicles from capacity for DYNA 930.8
! MaxFlowRate(i) is already corrected (reduced for presence of left turn vehicles and heavy trucks
! therefore MaxFlowRate(i)/SatFlowRate(i) is less than 1.0
!				right_capacity(i)=right_capacity(i)-(MaxFlowRate(i)/SatFlowRate(i))*mtnum(j)
					right_capacity(i)=right_capacity(i)-
     +		(MaxFlowRateOrig(i)/SatFlowRate(i))*mtnum(j)

				else
				right_capacity(i)=right_capacity(i)-1.0 
				endif
			endif

			intoo(nl)%NVehIn=intoo(nl)%NVehIn+1
			call TranLink_Insert(nl,intoo(nl)%NVehIn,1,j)
			call TranLink_Insert(nl,intoo(nl)%NVehIn,2,i)
			call TranLink_Insert(nl,intoo(nl)%NVehIn,3,kj)
		endif

		if(bayR(i).eq.0)then					! without right turn bay
		if(captot(i).gt.0)then
			if(link_iden(i).eq.1.or.link_iden(i).eq.2)then !capacity in freeway is in pcphpl, so need to factor in PCE when determining # of vehicles to move
				if(qflag(j))then


!the number of vehicles from capacity for DYNA 930.8
! MaxFlowRate(i) is already corrected (reduced for presence of left turn vehicles and heavy trucks
! therefore MaxFlowRate(i)/SatFlowRate(i) is less than 1.0
!				right_capacity(i)=right_capacity(i)-(MaxFlowRate(i)/SatFlowRate(i))*mtnum(j)
				right_capacity(i)=right_capacity(i)-
     +			(MaxFlowRateOrig(i)/SatFlowRate(i))*mtnum(j)
				else
	right_capacity(i)=right_capacity(i)-1.0*mtnum(j) 
			    endif
		   else ! capacity in arterials is in vphpl and is computed using MaxFlowRate
				if(qflag(j))then

!the number of vehicles from capacity for DYNA 930.8
! MaxFlowRate(i) is already corrected (reduced for presence of left turn vehicles and heavy trucks
! therefore MaxFlowRate(i)/SatFlowRate(i) is less than 1.0
!				right_capacity(i)=right_capacity(i)-(MaxFlowRate(i)/SatFlowRate(i))*mtnum(j)
	right_capacity(i)=right_capacity(i)-
     +  (MaxFlowRateOrig(i)/SatFlowRate(i))*mtnum(j)
				else
	right_capacity(i)=right_capacity(i)-1.0 
				endif
		  endif
		 
		captot(i)=captot(i)-1			!need to reduce tot capacity as well
          intoo(nl)%NVehIn=intoo(nl)%NVehIn+1
          call TranLink_Insert(nl,intoo(nl)%NVehIn,1,j)
          call TranLink_Insert(nl,intoo(nl)%NVehIn,2,i)
          call TranLink_Insert(nl,intoo(nl)%NVehIn,3,kj)

		endif
			endif
!*****************************End of addition**********************************

! --
! --if the vehicle is making movements other than left or right turn
!   then check if there is residual total capacity as well as 
!the available capacity for each movement.
! --

		elseif((capacity(i,nlindex)).gt.0.and.(captot(i)).gt.0)then

c	if(j.eq.4092)then
c	print *,'Alex_Other'
c	pause
c	endif

!      elseif((capacity(i,nlindex)).gt.0) then
				if(link_iden(i).eq.1.or.link_iden(i).eq.2)then 
	!capacity in freeway is in pcphpl, so need to factor in PCE 
	!when determining # of vehicles to move
					if(qflag(j))then

!the number of vehicles from capacity for DYNA 930.8
! MaxFlowRate(i) is already corrected (reduced for presence of left turn vehicles and heavy trucks
! therefore MaxFlowRate(i)/SatFlowRate(i) is less than 1.0
!				right_capacity(i)=right_capacity(i)-(MaxFlowRate(i)/SatFlowRate(i))*mtnum(j)
					right_capacity(i)=right_capacity(i)-
     +				(MaxFlowRateOrig(i)/SatFlowRate(i))*mtnum(j)		
					else
        capacity(i,nlindex)=capacity(i,nlindex)-1.0*mtnum(j) 
					endif
				else ! capacity in arterials is in vphpl and is computed using MaxFlowRate
					if(qflag(j))then

!the number of vehicles from capacity for DYNA 930.8
! MaxFlowRate(i) is already corrected (reduced for presence of left turn vehicles and heavy trucks
! therefore MaxFlowRate(i)/SatFlowRate(i) is less than 1.0
!				right_capacity(i)=right_capacity(i)-(MaxFlowRate(i)/SatFlowRate(i))*mtnum(j)
	right_capacity(i)=right_capacity(i)-
     +  (MaxFlowRateOrig(i)/SatFlowRate(i))*mtnum(j)		
					else
	capacity(i,nlindex)=capacity(i,nlindex)-1.0 
					endif
				endif

				captot(i)=captot(i)-1 
				intoo(nl)%NVehIn=intoo(nl)%NVehIn+1
				call TranLink_Insert(nl,intoo(nl)%NVehIn,1,j)
				call TranLink_Insert(nl,intoo(nl)%NVehIn,2,i)
				call TranLink_Insert(nl,intoo(nl)%NVehIn,3,kj)

!         intooi(nl,intoo(nl)%NVehIn,1)=j
!         intooi(nl,intoo(nl)%NVehIn,2)=i
!         intooi(nl,intoo(nl)%NVehIn,3)=kj

       else
! --
! --if the vehicle will wait in the queue on the current link
! --
				qflag(j)=.True.
				xpar(j)=0.0

				tqwait(j)=tqwait(j)+tleft(j)
				ttilnow(j)=ttilnow(j)+tleft(j)			
				
c        if((abs(t-(endtime-1)*tii).lt.0.001).and.realdm.ne.1)then
c           call links_travel_time(i,j,t)
c        endif	

				ttstop(j)=ttstop(j)+tleft(j)
! --     add to GUITotalTime
				GuiTotalTime=GuiTotalTime+tleft(j)

c	if(j.eq.4092)then
c	print *,'AlexWaiting'
c	pause
c	endif
       endif
      endif
      endif ! HGF endif 

8     if(associated(p_mtxj_value%next_veh))then 
		p_mtxj_value=>p_mtxj_value%next_veh
      endif

      enddo ! endof of do while loop
! --
! --
c	if(iteration.gt.0)print *, 'Alex11290'  
7     continue

      return
      end
