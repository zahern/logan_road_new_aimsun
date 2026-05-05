      	subroutine outputmuc
	
      	use muc_mod

!  -- determine number of vehicle from i,to j at assingment interval t
      	do j = 1, jj
       	nt = ifix(((stime(j)-stagest)/tii)/tad)+1
       	if(vehclass(j).eq.2.and.stime(j).ge.stagest) then !SO veh
c	print *, 'AlexSO'
        if(ioc(j).eq.1) then

!        sonxz_lov(idnod(isec(j)),MasterDest(jdest(j)),nt)=sonxz_lov(idnod(isec(j)),MasterDest(jdest(j)),nt)+1
        sonxz_lov(jorigin(j),MasterDest(jdest(j)),nt)=
     +  sonxz_lov(jorigin(j),MasterDest(jdest(j)),nt)+1
!	  sopolicy_lov(idnod(isec(j)),MasterDest(jdest(j)),nt,1)%NumOfVehicle=sopolicy_lov(idnod(isec(j)),MasterDest(jdest(j)),nt,1)%NumOfVehicle + 1
	sopolicy_lov(jorigin(j),MasterDest(jdest(j)),nt,1)%NumOfVehicle=
     + sopolicy_lov(jorigin(j),MasterDest(jdest(j)),nt,1)%NumOfVehicle+1
	  else
!        sonxz_hov(idnod(isec(j)),MasterDest(jdest(j)),nt)=sonxz_hov(idnod(isec(j)),MasterDest(jdest(j)),nt)+1
        sonxz_hov(jorigin(j),MasterDest(jdest(j)),nt)=
     +  sonxz_hov(jorigin(j),MasterDest(jdest(j)),nt)+1
!	  sopolicy_hov(idnod(isec(j)),MasterDest(jdest(j)),nt,1)%NumOfVehicle=sopolicy_hov(idnod(isec(j)),MasterDest(jdest(j)),nt,1)%NumOfVehicle + 1
	sopolicy_hov(jorigin(j),MasterDest(jdest(j)),nt,1)%NumOfVehicle=
     + sopolicy_hov(jorigin(j),MasterDest(jdest(j)),nt,1)%NumOfVehicle+1
	  endif

       	elseif(vehclass(j).eq.3.and.stime(j).ge.stagest) then !UE veh
c	print *, 'AlexUE'
        if(ioc(j).eq.1) then

! 	  uenxz_lov(idnod(isec(j)),MasterDest(jdest(j)),nt)=uenxz_lov(idnod(isec(j)),MasterDest(jdest(j)),nt)+1
 	  uenxz_lov(jorigin(j),MasterDest(jdest(j)),nt)=
     +  uenxz_lov(jorigin(j),MasterDest(jdest(j)),nt)+1
!	  uepolicy_lov(idnod(isec(j)),MasterDest(jdest(j)),nt,1)%NumOfVehicle=uepolicy_lov(idnod(isec(j)),MasterDest(jdest(j)),nt,1)%NumOfVehicle + 1
	uepolicy_lov(jorigin(j),MasterDest(jdest(j)),nt,1)%NumOfVehicle=
     + uepolicy_lov(jorigin(j),MasterDest(jdest(j)),nt,1)%NumOfVehicle+1
	  else
! 	  uenxz_hov(idnod(isec(j)),MasterDest(jdest(j)),nt)=uenxz_hov(idnod(isec(j)),MasterDest(jdest(j)),nt)+1
 	  uenxz_hov(jorigin(j),MasterDest(jdest(j)),nt)=
     +  uenxz_hov(jorigin(j),MasterDest(jdest(j)),nt)+1
!	  uepolicy_hov(idnod(isec(j)),MasterDest(jdest(j)),nt,1)%NumOfVehicle=uepolicy_hov(idnod(isec(j)),MasterDest(jdest(j)),nt,1)%NumOfVehicle + 1
	uepolicy_hov(jorigin(j),MasterDest(jdest(j)),nt,1)%NumOfVehicle=
     + uepolicy_hov(jorigin(j),MasterDest(jdest(j)),nt,1)%NumOfVehicle+1
	  endif

       	endif
      	enddo 

      	return
      	end
